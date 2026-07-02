#!/usr/bin/env python3
"""
suivi_go.py — SUIVI des "go" de The Wire. Parano, prouve, ZERO invention.

IDEE : data/go_suivi.json n'est jamais une source de verite, c'est un INDEX DERIVE.
On le regenere a chaque fois depuis les VRAIES sources :
  - data/go_traites.json        -> quels moves ont ete lances (cle "date_radar|_id")
  - briefs/AAAA-MM-JJ_radar.json -> le contenu du move (title, do_now, projet, meta)
  - data/feedback_events.jsonl  -> events "paye"/"fait" tapes par Adam (feedback.py)
  - data/go_confirmations.jsonl -> confirmations directes d'Adam (fait/skip/paye)
  - le VRAI git de chaque projet -> commits DATES posterieurs au lancement

HIERARCHIE DES SOURCES (autorite decroissante — la plus haute gagne toujours) :
  confirmation Adam  >  event feedback  >  commit git date  >  hypothese LLM.

REGLES DURES (anti-hallu, codees, pas juste ecrites) :
  1. "paye" + montant : UNIQUEMENT via event feedback type=paye OU confirmation Adam.
     Le LLM ne peut JAMAIS produire "paye". Le parseur LLM refuse ce verdict.
  2. "fait" prouve : event/confirmation "fait", OU un commit dont le message reprend
     >=2 mots-cles du move (_commit_matche_move). Sinon au mieux "projet_bouge".
  3. Le LLM (etage 2) plafonne a "probablement_fait" (hypothese, confiance<1, preuve
     citee). Il ne rentre JAMAIS dans preuves[], seulement dans hypotheses[].
  4. Aucun commit / aucun event -> "lance" (recent), "dormant" (>= 5 jours), puis
     "dormant_archive" (> 21 jours sans la moindre preuve : sort du radar quotidien
     mais RESTE dans go_suivi.json — jamais de suppression). Rien n'est suppose.
  5. Toute hypothese LLM dont la "preuve_citee" ne reprend pas un fragment reel d'un
     commit fourni est REJETEE (_preuve_est_reelle).

Le LLM (etage 2) est appele RAREMENT et a la demande : seulement sur un go
"projet_bouge" sans event, rate-limite a 24h par go, plafonne a MAX_LLM_PAR_RUN.
La plupart des jours : 0 token.

Stdlib pure + subprocess (git / claude optionnel). Robuste Windows, console ASCII.

CLI :
  python systeme/suivi_go.py --refresh          # regenere go_suivi.json (0 token)
  python systeme/suivi_go.py --radar            # imprime la section "Tes go en cours"
  python systeme/suivi_go.py --statut           # imprime le detail complet
  python systeme/suivi_go.py --llm <cle> [--force]   # etage 2 sur un go precis
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ecriture atomique (audit Fable, P1-4) : go_suivi.json ne doit jamais etre
# tronque par un crash mid-write.
try:
    from atomic_io import write_json_atomic
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from atomic_io import write_json_atomic

# Config projets unifiee (audit Fable, reco #4) : data/projets.json en priorite,
# NOMS_AFFICHAGE fige en repli si absent/corrompu -> zero regression possible.
try:
    import config_projets as _cp
except ImportError:
    _cp = None

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
BRIEFS = ROOT / "briefs"

GO_TRAITES = DATA / "go_traites.json"
HORODATAGE = DATA / "go_horodatage.json"   # instant reel de chaque go (ecrit par executer_move)
SNAPSHOTS = DATA / "go_snapshots.json"     # move FIGE au moment du go (source auto-portante)
ATELIER = DATA / "atelier.json"
FEEDBACK = DATA / "feedback_events.jsonl"
CONFIRM = DATA / "go_confirmations.jsonl"   # append-only : confirmations directes d'Adam
OUT = DATA / "go_suivi.json"

# Noms d'AFFICHAGE : le suivi montre le nom PRODUIT (celui qu'Adam utilise), jamais le
# nom technique du dossier. Cle = nom normalise (via _norm), valeur = joli nom. Les radars
# ecrivent tantot 'serp-scraper' tantot 'BrandPulse' selon les jours -> on unifie ici.
NOMS_AFFICHAGE = {
    "serpscraper": "BrandPulse",
    "brandpulse": "BrandPulse",
    "brandpulseai": "BrandPulse",
    "claudeeatstokens": "Claude Eats Tokens",
    "cet": "Claude Eats Tokens",
    "cuepoint": "Cuepoint",
    "mixhub": "Pacto Club",
    "pacto": "Pacto Club",
    "pactoclub": "Pacto Club",
}

JOURS_DORMANT = 5           # 0 mouvement depuis N jours -> "dormant" (fait dur, pas suppose)
JOURS_ARCHIVE = 21          # dormant sans AUCUNE preuve depuis > N jours -> "dormant_archive" :
                            # sort du radar quotidien (bruit) mais RESTE dans go_suivi.json et
                            # est COMPTE dans le statut complet. Archivage = jamais suppression.
MAX_LLM_PAR_RUN = 3         # jamais plus de N appels LLM dans un seul passage
LLM_RATE_LIMIT_H = 24       # un go n'est re-interroge par le LLM qu'apres N heures
LLM_COMMITS_MAX = 8         # on ne montre au LLM que les N derniers commits (prompt compact)
LLM_CONF_MIN = 0.55         # sous ce seuil, l'hypothese LLM est ignoree

# On importe le routage de executer_move.py : SOURCE UNIQUE du mapping projet->dossier.
try:
    from executer_move import ALIAS, _norm, _index_atelier, resoudre_dossier  # type: ignore
except Exception:
    # Fallback autonome (si import indisponible, ex: appel hors dossier systeme).
    ALIAS = {}

    _ACCENTS = str.maketrans("àáâãäçèéêëìíîïñòóôõöùúûüýÿ", "aaaaaceeeeiiiinooooouuuuyy")

    def _norm(s: str) -> str:  # type: ignore
        s = (s or "").strip().lower().translate(_ACCENTS)
        return re.sub(r"[\s\-_]+", "", s)

    def _index_atelier() -> dict:  # type: ignore
        idx = {}
        try:
            at = json.loads(ATELIER.read_text(encoding="utf-8"))
        except Exception:
            at = {}
        for e in at.get("projets", []) or []:
            if e.get("nom") and e.get("chemin"):
                idx[_norm(e["nom"])] = e["chemin"]
        return idx

    def resoudre_dossier(projet_radar: str):  # type: ignore
        idx = _index_atelier()
        key = _norm(projet_radar)
        cible = ALIAS.get(key, projet_radar)
        chemin = idx.get(_norm(cible)) or idx.get(key)
        if chemin and Path(chemin).is_dir():
            return chemin, None
        return None, f"dossier introuvable pour '{projet_radar}'"


# ------------------------------------------------------------------------------
# IO + utilitaires
# ------------------------------------------------------------------------------

def _safe(s) -> str:
    """Console Windows cp1252 : jamais de crash sur un accent/emoji."""
    return str(s).encode("ascii", "replace").decode("ascii")


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _lire_jsonl(p: Path) -> list:
    if not p.exists():
        return []
    out = []
    for ligne in p.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne:
            try:
                out.append(json.loads(ligne))
            except Exception:
                pass
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(s: str):
    """Accepte 'AAAA-MM-JJ' (events feedback) OU ISO datetime (dernier_commit).
    Retourne un datetime aware (UTC si naif), ou None."""
    if not s:
        return None
    txt = str(s).strip()
    try:
        if len(txt) == 10 and txt[4] == "-" and txt[7] == "-":
            d = datetime.strptime(txt, "%Y-%m-%d")
        else:
            d = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _jours_depuis(s: str) -> float:
    d = _parse_date(s)
    return (_now() - d).total_seconds() / 86400.0 if d else 0.0


def _apres(candidat: str, borne: str) -> bool:
    """True si la date 'candidat' est STRICTEMENT posterieure a 'borne'.
    Comparaison au jour pres quand l'une des deux n'a pas d'heure (events = jour)."""
    dc, db = _parse_date(candidat), _parse_date(borne)
    if not dc or not db:
        return False
    return dc.date() > db.date() or (dc.date() == db.date() and dc > db)


# ------------------------------------------------------------------------------
# Sources : lancements, radars, events, confirmations, projets
# ------------------------------------------------------------------------------

def _radars_par_date() -> dict:
    out = {}
    for p in sorted(BRIEFS.glob("*_radar.json")):
        r = _load(p, None)
        if isinstance(r, dict):
            out[r.get("date") or p.name.replace("_radar.json", "")] = r
    return out


def _move_par_id(radar: dict, move_id: str):
    for m in (radar or {}).get("moves", []) or []:
        if m.get("_id") == move_id:
            return m
    return None


def _events_feedback() -> list:
    return _lire_jsonl(FEEDBACK)


def _confirmations() -> dict:
    """go_confirmations.jsonl (append-only) -> derniere confirmation par cle.
    Une confirmation : {cle, quoi(fait|skip|paye), montant, date, texte_brut}."""
    out = {}
    for rec in _lire_jsonl(CONFIRM):
        cle = rec.get("cle")
        if cle:
            out[cle] = rec  # la derniere ligne d'une cle ecrase les precedentes
    return out


def _atelier_index() -> dict:
    """{ nom_normalise -> entree_projet } depuis atelier.json."""
    idx = {}
    at = _load(ATELIER, {})
    for e in at.get("projets", []) or []:
        if e.get("nom"):
            idx[_norm(e["nom"])] = e
    return idx


def _entree_projet(projet_radar: str) -> dict:
    """Entree atelier.json du projet d'un move (via alias + normalisation)."""
    idx = _atelier_index()
    key = _norm(projet_radar)
    cible = ALIAS.get(key, projet_radar)
    return idx.get(_norm(cible)) or idx.get(key) or {}


# ------------------------------------------------------------------------------
# ETAGE 1 : signaux git DETERMINISTES (le vrai git du projet, dates strictes)
# ------------------------------------------------------------------------------

def _borne_a_une_heure(depuis_iso: str) -> bool:
    """True si la borne de lancement porte une heure reelle (horodatage du go), False si
    c'est une date nue normalisee a minuit (repli sur la date du radar)."""
    txt = str(depuis_iso or "").strip()
    if len(txt) == 10 and txt.count("-") == 2:   # 'AAAA-MM-JJ' pur
        return False
    d = _parse_date(txt)
    if not d:
        return False
    return not (d.hour == 0 and d.minute == 0 and d.second == 0)


def _git_commits_apres(projet_dir: str, depuis_iso: str) -> list:
    """Interroge le VRAI git du projet. Retourne [{hash, date, message}] des commits
    STRICTEMENT posterieurs a 'depuis_iso'. [] si pas de git / erreur / rien.

    Anti faux-positif "commit du matin" : si la borne n'a PAS d'heure reelle (repli sur
    la date du radar, donc minuit), on exige un commit d'un JOUR strictement posterieur
    -> un commit fait le matin AVANT ta reponse 'go' de l'apres-midi ne compte pas. Quand
    on a l'instant reel du go (horodatage), la comparaison stricte a l'instant suffit."""
    if not projet_dir or not Path(projet_dir, ".git").exists():
        return []
    d = _parse_date(depuis_iso)
    since = d.strftime("%Y-%m-%dT%H:%M:%S") if d else "1970-01-01"
    a_heure = _borne_a_une_heure(depuis_iso)
    try:
        out = subprocess.run(
            ["git", "-C", projet_dir, "log", f"--since={since}",
             "--pretty=format:%H%x1f%cI%x1f%s", "--no-merges", "-n", "50"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        ).stdout
    except Exception:
        return []
    commits = []
    for ligne in out.splitlines():
        parts = ligne.split("\x1f")
        if len(parts) != 3:
            continue
        h, cdate, msg = parts
        dc = _parse_date(cdate)
        if not dc or not d:
            continue
        if a_heure:
            ok = dc > d                       # instant reel connu : strictement apres
        else:
            ok = dc.date() > d.date()         # borne a minuit : exiger un JOUR strictement apres
        if ok:
            commits.append({"hash": h[:8], "date": cdate, "message": msg})
    return commits


_STOP = {
    "the", "and", "for", "les", "des", "une", "pour", "avec", "sur", "dans", "ton",
    "ta", "tes", "ton", "est", "sont", "que", "qui", "quoi", "add", "fix", "update",
    "wip", "chore", "docs", "test", "refactor", "un", "de", "du", "la", "le", "a",
    "to", "of", "in", "on", "it", "is", "be", "doit", "etre", "liste", "new",
}


def _mots(texte: str) -> set:
    toks = re.findall(r"[a-zA-Zàâçéèêëîïôûùüÿœ0-9]{3,}", (texte or "").lower())
    return {t for t in toks if t not in _STOP}


def _commit_matche_move(commit_msg: str, move: dict) -> bool:
    """Un commit "prouve" le move seulement si son message partage >=2 mots-cles
    significatifs avec le titre + do_now du move. Anti-faux-positif (un commit random
    ne doit pas passer un move a 'fait')."""
    ref = _mots(move.get("title", "")) | _mots(move.get("do_now", ""))
    ref |= _mots(move.get("pourquoi_maintenant", ""))
    communs = ref & _mots(commit_msg)
    return len(communs) >= 2


# Mots trop GENERIQUES pour prouver a eux seuls qu'un STEP precis est fait : ils
# apparaissent dans presque tous les commits d'un projet web. Un step ne matche un
# commit que s'ils partagent au moins un mot HORS de cette liste (mot specifique).
# (Ex du faux positif corrige : 'auditer le repo concurrent' matchait 'clean repo,
#  rewrite readme' via repo+readme seuls -> declarait a tort le step 'fait'.)
_STOP_STEP = {
    "repo", "readme", "page", "post", "poste", "poster", "app", "code", "note",
    "noter", "fichier", "lien", "liens", "pricing", "prix", "site", "web", "doc",
    "readme", "ouvre", "ouvrir", "lis", "lire", "regarde", "regarder", "ecris",
    "ecrire", "rediger", "redige", "ajoute", "ajouter", "cree", "creer", "projet",
}


def _commit_matche_step(commit_msg: str, titre: str, how: str) -> bool:
    """Un commit prouve un STEP seulement s'il partage >=2 mots-cles avec le step ET
    qu'au moins un de ces mots communs est SPECIFIQUE (hors _STOP_STEP). Sinon un
    commit generique du projet ('clean repo, rewrite readme') matcherait n'importe
    quel step mentionnant 'repo' -> fait invente. C'est le garde-fou anti-hallu du
    matching step-par-commit (plus strict que _commit_matche_move, car un step a peu
    de mots)."""
    ref = _mots(titre) | _mots(how)
    communs = ref & _mots(commit_msg)
    if len(communs) < 2:
        return False
    # au moins un mot commun doit etre SPECIFIQUE (sinon = 2 mots passe-partout).
    return any(m not in _STOP_STEP for m in communs)


# ------------------------------------------------------------------------------
# ETAGE 1bis : signaux de TRAVAIL EN COURS (au-dela du seul commit git)
# ------------------------------------------------------------------------------

def _travail_en_cours(projet_dir: str, date_lancement: str) -> dict:
    """Detecte un travail EN COURS meme SANS commit : c'est ce qui manquait au suivi
    ('ca bosse mais ca dit aucun signe'). Trois capteurs FACTUELS, tous citables :
      - git status --porcelain non vide  -> fichiers modifies/ajoutes non commites ;
      - THE-WIRE-MOVE.md present a la racine ET modifie apres le go -> session lancee
        pour CE move (executer_move depose ce fichier au lancement) ;
      - un fichier du repo modifie (mtime) apres le go -> le projet vit.
    Retourne {en_cours: bool, detail: str, date: iso} (detail = la preuve a afficher)."""
    if not projet_dir or not Path(projet_dir).is_dir():
        return {"en_cours": False, "detail": "", "date": ""}
    d0 = _parse_date(date_lancement)

    # (a) travail non committe (le plus parlant : "tu bosses, pas encore committe")
    try:
        porcelain = subprocess.run(
            ["git", "-C", projet_dir, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        ).stdout.strip()
    except Exception:
        porcelain = ""
    if porcelain:
        n = len([l for l in porcelain.splitlines() if l.strip()])
        return {"en_cours": True,
                "detail": f"{n} fichier(s) modifie(s) non commite(s)", "date": _now().isoformat()}

    # (b) THE-WIRE-MOVE.md depose pour ce move, recent (post-go)
    md = Path(projet_dir) / "THE-WIRE-MOVE.md"
    if md.exists():
        try:
            mt = datetime.fromtimestamp(md.stat().st_mtime, tz=timezone.utc)
            if not d0 or mt >= d0:
                return {"en_cours": True, "detail": "session The Wire ouverte (move depose)",
                        "date": mt.isoformat()}
        except Exception:
            pass

    # (c) un fichier du repo modifie apres le go (le projet vit sans commit ni status)
    try:
        recent = None
        for p in Path(projet_dir).rglob("*"):
            if ".git" in p.parts or not p.is_file():
                continue
            mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if d0 and mt > d0 and (recent is None or mt > recent):
                recent = mt
        if recent is not None:
            return {"en_cours": True, "detail": "fichiers modifies depuis le go",
                    "date": recent.isoformat()}
    except Exception:
        pass

    return {"en_cours": False, "detail": "", "date": ""}


# ------------------------------------------------------------------------------
# ETAGE 1ter : DETAIL "ou on en est" d'un go (Fait / En cours / Reste)
#   100% factuel : chaque ligne s'appuie sur un commit reel ou un fichier reel.
#   Formatage deterministe, ZERO token, ZERO invention.
# ------------------------------------------------------------------------------

_HEURES_STOP = {
    "brouillons", "brouillon", "comm", "the", "wire", "move", "section",
    "urls", "url", "reel", "reels", "reelles", "repo", "pages",
}


def _heure_locale(iso: str) -> str:
    """'2026-07-01T16:43:29+02:00' -> '16h43'. '' si date illisible.
    On garde l'heure LOCALE telle qu'ecrite (offset porte par l'ISO), pas d'UTC."""
    d = _parse_date(iso)
    if not d:
        return ""
    return f"{d.hour:02d}h{d.minute:02d}"


def _il_y_a(iso: str) -> str:
    """Heure relative lisible depuis maintenant : 'a l'instant', 'il y a 3 min',
    'il y a 2 h', 'hier', 'il y a 4 j'. '' si date illisible."""
    d = _parse_date(iso)
    if not d:
        return ""
    secs = (_now() - d).total_seconds()
    if secs < 0:
        secs = 0
    mins = int(secs // 60)
    if mins < 1:
        return "a l'instant"
    if mins < 60:
        return f"il y a {mins} min"
    heures = mins // 60
    if heures < 24:
        return f"il y a {heures} h"
    jours = heures // 24
    if jours == 1:
        return "hier"
    return f"il y a {jours} j"


def _resume_commit(msg: str, max_len: int = 48) -> str:
    """Resume LISIBLE d'un message de commit (ne tronque pas betement au milieu d'un mot).
    - coupe au premier ' : ' / ' — ' / '(' pour garder la tete de phrase la plus dense ;
    - sinon coupe a la limite de mot <= max_len, ajoute '...' si on a coupe.
    N'INVENTE rien : c'est le message reel, juste raccourci proprement."""
    m = (msg or "").strip()
    if not m:
        return ""
    # tete de phrase avant un separateur structurant, si elle est deja informative
    for sep in (" : ", " — ", " - ", " ("):
        i = m.find(sep)
        if 8 <= i <= max_len:
            return m[:i].strip()
    if len(m) <= max_len:
        return m
    coupe = m[:max_len]
    esp = coupe.rfind(" ")
    if esp >= 12:
        coupe = coupe[:esp]
    return coupe.rstrip(" ,;:-") + "..."


def _nom_court(fichier: str) -> str:
    """'posts/aeo-geo-launch-post.md' -> 'aeo-geo-launch-post.md' (basename lisible)."""
    return fichier.replace("\\", "/").rstrip("/").split("/")[-1] or fichier


def _nature_fichier(chemin: str) -> str:
    """Etiquette FACTUELLE d'un fichier a partir de son chemin/extension (pas de contenu)."""
    c = chemin.replace("\\", "/").lower()
    base = c.split("/")[-1]
    ext = base.rsplit(".", 1)[-1] if "." in base else ""
    if base == "app.py":
        return "code Python (app principale)"
    if ext == "py":
        return "code Python"
    if c.startswith("posts/") and ext in ("md", "markdown"):
        return "brouillon de post"
    if ext in ("md", "markdown"):
        return "note Markdown"
    if ext in ("html", "htm"):
        return "page web HTML"
    if ext in ("css", "scss"):
        return "feuille de style"
    if ext in ("js", "ts", "jsx", "tsx"):
        return "code front"
    if ext == "json":
        return "config/donnees JSON"
    return f"fichier .{ext}" if ext else "fichier"


def _mtime_iso_reelle(abs_p: Path) -> str:
    """VRAIE date de modif d'un chemin, TOUJOURS lue via os.stat().st_mtime, jamais devinee.
    Renvoie l'ISO local, ou '' si aucune mtime fiable n'est lisible.

    - Fichier reel                -> son st_mtime.
    - Dossier untracked collapse  -> le st_mtime du fichier REEL le plus recent qu'il
      contient (git remonte 'posts/' ou '.vscode/' sans mtime ; on lit une vraie mtime
      disque a l'interieur au lieu d'afficher une date trompeuse ou rien).
    - Rien de lisible             -> '' (l'appelant n'affichera alors AUCUNE date, plutot
      qu'une fausse : une date affichee doit etre VRAIE ou absente).

    RÈGLE ANTI-HALLU : on ne renvoie une date QUE si elle vient d'un os.stat() reel d'un
    fichier reel presente par git. On n'attribue jamais la mtime d'un homonyme (le suivi
    lit le fichier que git remonte, tel quel)."""
    try:
        if abs_p.is_file():
            ts = os.stat(abs_p).st_mtime
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat()
    except Exception:
        return ""
    # Dossier collapse : chercher la mtime reelle la plus recente d'un fichier a l'interieur.
    try:
        if abs_p.is_dir():
            recent = None
            for p in abs_p.rglob("*"):
                try:
                    if p.is_file():
                        mt = os.stat(p).st_mtime
                        if recent is None or mt > recent:
                            recent = mt
                except Exception:
                    continue
            if recent is not None:
                return datetime.fromtimestamp(recent, tz=timezone.utc).astimezone().isoformat()
    except Exception:
        pass
    return ""


def _fichiers_non_commites(projet_dir: str) -> list:
    """Relit le VRAI git status du projet et renvoie, par fichier modifie/ajoute non
    commite : {etat, fichier, mtime_iso, nature}. mtime = vraie date de modif sur disque,
    TOUJOURS via os.stat().st_mtime du chemin que git remonte (fichier reel ; pour un
    dossier untracked collapse, la mtime reelle du fichier le plus recent a l'interieur).
    Jamais de date inventee : mtime='' quand rien de fiable n'est lisible (l'appelant
    n'affiche alors aucune date plutot qu'une fausse). [] si pas de git / rien."""
    if not projet_dir or not Path(projet_dir, ".git").exists():
        return []
    try:
        raw = subprocess.run(
            ["git", "-C", projet_dir, "status", "--porcelain", "-z"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        ).stdout
    except Exception:
        return []
    out = []
    for entry in raw.split("\x00"):
        if not entry or len(entry) < 4:
            continue
        etat = entry[:2].strip()
        chemin = entry[3:]
        if not chemin:
            continue
        # git remonte le chemin tel quel (ex 'demo-brandpulseapp.gif' a la racine, ou
        # '.vscode/' collapse). On lit la mtime REELLE de CE chemin, jamais d'un homonyme.
        abs_p = Path(projet_dir) / chemin
        mtime_iso = _mtime_iso_reelle(abs_p)
        out.append({
            "etat": etat, "fichier": chemin.replace("\\", "/"),
            "mtime": mtime_iso, "nature": _nature_fichier(chemin),
        })
    return out


def _regrouper_fichiers(fichiers: list) -> str:
    """Rend les fichiers non commites en une phrase lisible, groupee par dossier quand
    il y en a beaucoup, avec la modif la plus recente en horloge relative.
    Ex peu de fichiers : 'app.py, index.html + compare.html, post AEO/GEO — modifies il y a 3 min'.
    Ex beaucoup : '3 dans web/, 2 a la racine — modifies il y a 3 min'."""
    if not fichiers:
        return ""
    # mtime le plus recent du lot -> une seule horloge relative pour tout le groupe
    mtimes = [f["mtime"] for f in fichiers if f.get("mtime")]
    recent = max(mtimes) if mtimes else ""
    horloge = _il_y_a(recent) if recent else ""

    # un chemin finissant par '/' est un DOSSIER untracked collapse par git
    # (ex 'posts/') : on le NOMME comme dossier, jamais comme "1 dans posts/".
    noms = []
    for f in fichiers:
        ch = f["fichier"]
        noms.append(f"le dossier {_nom_court(ch)}/" if ch.endswith("/") else _nom_court(ch))
    if len(fichiers) <= 4:
        corps = ", ".join(noms)
    else:
        # groupement par dossier de tete. Un chemin finissant par '/' est un
        # DOSSIER untracked collapse par git (ex 'posts/') : on le nomme comme
        # dossier, pas comme "N fichiers dans ...".
        par_dossier = {}
        dossiers_collapses = []
        for f in fichiers:
            chemin = f["fichier"]
            if chemin.endswith("/"):
                dossiers_collapses.append(chemin)  # ex 'posts/'
                continue
            dossier = chemin.rsplit("/", 1)[0] + "/" if "/" in chemin else "racine"
            par_dossier[dossier] = par_dossier.get(dossier, 0) + 1
        morceaux = [f"{n} dans {d}" if d != "racine" else f"{n} a la racine"
                    for d, n in sorted(par_dossier.items(), key=lambda kv: -kv[1])]
        # dossiers entiers non suivis : "le dossier posts/"
        morceaux += [f"le dossier {d}" for d in sorted(dossiers_collapses)]
        corps = ", ".join(morceaux)

    suffixe = f" — modifie(s) {horloge}" if horloge else ""
    return corps + suffixe


def _troncature_move(do_now: str, max_len: int = 160) -> str:
    """Raccourcit un do_now long pour Telegram, a la limite de mot, sans le denaturer."""
    d = do_now.strip()
    if len(d) <= max_len:
        return d
    coupe = d[:max_len]
    esp = coupe.rfind(" ")
    if esp >= 20:
        coupe = coupe[:esp]
    return coupe.rstrip(" ,;:-") + "..."


# ------------------------------------------------------------------------------
# ETAGE 1quater : "Ce que ce go a produit" — steps du plan MAPPES a leur preuve.
#   Hierarchie de preuve (la 1re qui matche gagne, on ne monte jamais d'un cran) :
#     1. COMMIT post-go dont le message matche le step        -> FAIT (systeme, horodate)
#     2. FICHIER cite par le step, mtime >= date_lancement     -> FAIT (systeme, relu disque)
#     3. DIGEST citant un fichier present ET post-go           -> FAIT (le digest a POINTE)
#     4. DIGEST seul (action externe, pas de fichier)         -> FAIT SELON CLAUDE CODE (cite)
#     5. DIGEST RESTE : step liste en ## RESTE                 -> RESTE (dit par Claude Code)
#     6. rien                                                  -> on ne declare rien
#   Le digest THE-WIRE-DIGEST.md est un TEMOIGNAGE (ecrit par l'agent qui a agi), jamais
#   une base de verite : une ligne non recoupee par un fichier/commit reel reste
#   ATTRIBUEE ("d'apres Claude Code"), elle ne produit JAMAIS un "fait systeme".
#   100% deterministe (parse + matching + rendu), ZERO token, ZERO invention.
# ------------------------------------------------------------------------------

# '- [step 2] ...' -> capture le numero et le corps de la puce.
_RE_STEP = re.compile(r"^\s*\[step\s*([0-9]{1,2})\]\s*(.*)$", re.I)
# 1re sous-chaine ressemblant a un chemin de fichier (a une extension). Ignore le
# decoratif '(3157 bytes, mtime ...)'. Barres avant/arriere, points, tirets acceptes.
_RE_CHEMIN = re.compile(r"[A-Za-z0-9_.\-/\\]+\.[A-Za-z0-9]{1,6}")


def _digest_puces(bloc: str) -> list:
    """Lignes puce '- ...' d'un bloc de section digest -> [texte sans le '- ']."""
    out = []
    for ligne in (bloc or "").splitlines():
        s = ligne.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
        elif s == "-":
            continue
    return out


def _digest_split_preuve(ligne: str):
    """'desc :: preuve' -> (desc, preuve). Sans ' :: ' -> (ligne, '') (tolerance :
    la ligne entiere devient la description, marquee 'd'apres Claude Code' a l'affichage)."""
    if " :: " in ligne:
        d, p = ligne.split(" :: ", 1)
        return d.strip(), p.strip()
    return ligne.strip(), ""


def _extraire_chemin(preuve: str) -> str:
    """1re sous-chaine ressemblant a un chemin de fichier dans une preuve (step/digest).
    '' si aucune. Normalise les backslash Windows en '/'."""
    m = _RE_CHEMIN.search(preuve or "")
    if not m:
        return ""
    return m.group(0).replace("\\", "/")


def _fichier_dur(projet_dir: str, chemin: str, date_lancement: str) -> str:
    """SEULE facon de promouvoir une ligne (step ou digest) en 'fait systeme' via fichier :
    renvoie l'ISO mtime si <chemin> existe SOUS le projet ET mtime >= date_lancement,
    sinon '' (fichier absent OU anterieur au go -> pas une preuve dure). Reutilise
    _mtime_iso_reelle (fichier reel uniquement, jamais un homonyme)."""
    if not chemin or not projet_dir:
        return ""
    abs_p = Path(projet_dir) / chemin
    iso = _mtime_iso_reelle(abs_p)
    if not iso:
        return ""
    d0, dm = _parse_date(date_lancement), _parse_date(iso)
    if d0 and dm and dm < d0:
        return ""   # fichier anterieur au go -> ce n'est pas une preuve de CE go
    return iso


def _lire_digest(projet_dir: str, date_lancement: str):
    """Parse THE-WIRE-DIGEST.md (racine projet). Pur fichier, ZERO git, ZERO LLM.
    Garde temporelle stricte : ignore si mtime < date_lancement (meme invariant que le
    capteur THE-WIRE-MOVE.md) -> un digest d'une session anterieure ne pollue pas le go
    courant. Tolerance totale au remplissage foireux : section absente = vide, ' :: '
    manquant = ligne entiere en description, jamais de crash. None si absent/anterieur."""
    if not projet_dir:
        return None
    p = Path(projet_dir) / "THE-WIRE-DIGEST.md"
    if not p.exists():
        return None
    d0 = _parse_date(date_lancement)
    try:
        mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except Exception:
        return None
    if d0 and mt < d0:          # digest d'une session anterieure au go -> ignore
        return None
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    # split sur les 5 en-tetes fixes '## FAIT|RESTE|OBSERVE|LIENS|NOTE' ; tete = front-matter.
    # LECON : OBSERVE doit etre un en-tete RECONNU. Sinon (bug d'origine) un '## OBSERVE'
    # entre RESTE et LIENS laissait 'cur' colle a RESTE -> les puces d'observation (ex.
    # "repo audite, aucun artefact") polluaient le RESTE et s'affichaient comme du travail
    # A FAIRE. Le declarer ici l'ISOLE : il ne contamine plus RESTE et devient citable
    # comme temoignage (jamais une preuve dure).
    sections = {"FAIT": "", "RESTE": "", "OBSERVE": "", "LIENS": "", "NOTE": ""}
    cur = None
    tete = {}
    for ligne in txt.splitlines():
        m = re.match(r"^\s*##\s+(FAIT|RESTE|OBSERVE|LIENS|NOTE)\b", ligne, re.I)
        if m:
            cur = m.group(1).upper()
            continue
        m2 = re.match(r"^\s*(MOVE|CLE|STATUT)\s*:\s*(.*)$", ligne, re.I)
        if m2 and cur is None:
            tete[m2.group(1).upper()] = m2.group(2).strip()
        if cur:
            sections[cur] += ligne + "\n"

    def _lignes(nom):
        res = []
        for puce in _digest_puces(sections[nom]):
            m = _RE_STEP.match(puce)
            n = int(m.group(1)) if m else None
            corps = m.group(2).strip() if m else puce
            desc, preuve = _digest_split_preuve(corps)
            res.append({"step": n, "desc": desc, "preuve": preuve})
        return res

    statut = ""
    if tete.get("STATUT"):
        bits = tete["STATUT"].split()
        statut = bits[0].lower() if bits else ""
    return {
        "statut": statut,
        "move": tete.get("MOVE", ""), "cle": tete.get("CLE", ""),
        "fait": _lignes("FAIT"), "reste": _lignes("RESTE"),
        # OBSERVE = ce que Claude Code a REGARDE sans produire d'artefact (audit lecture
        # seule). Parse a part pour ne pas polluer RESTE ; cite comme temoignage a
        # l'affichage, jamais promu en fait systeme.
        "observe": _lignes("OBSERVE"),
        "liens": _lignes("LIENS"), "note": sections["NOTE"].strip(),
        "mtime": mt.isoformat(),
    }


def _apparier_steps(steps, commits, digest, projet_dir, date_lancement) -> list:
    """Une entree par step du plan. Renvoie [{n, titre, etat, preuve, source}].
      etat   in {fait, reste, inconnu}
      source in {commit, fichier, digest_fichier, digest, ''}  (cf. hierarchie ci-dessus)
    RÈGLES DURES :
      - un step ne passe 'fait' QUE porte par (i) commit post-go matche, (ii) fichier
        dur >= go, ou (iii) une ligne digest. Jamais par deduction du 'how'.
      - une ligne digest ne devient JAMAIS source='fichier' : si elle pointe un fichier
        dur elle passe 'digest_fichier' (fait systeme, mais on garde la trace que c'est
        le digest qui a pointe) ; sinon 'digest' (attribue). Le digest ne surclasse
        jamais une preuve disque et ne peut jamais produire un 'fait' sans coche."""
    res = []
    # Un step peut avoir PLUSIEURS lignes FAIT dans le digest (ex 2 artefacts pour
    # "rediger un post"). On indexe par LISTE (pas un dict ecrasant) pour n'en perdre
    # aucune : on prend la 1ere qui porte une preuve DURE, sinon la 1ere tout court.
    dfait_n = {}
    for l in (digest["fait"] if digest else []):
        if l["step"]:
            dfait_n.setdefault(l["step"], []).append(l)
    dreste_n = {l["step"]: l for l in (digest["reste"] if digest else []) if l["step"]}
    dfait_libres = [l for l in (digest["fait"] if digest else []) if not l["step"]]

    for i, st in enumerate(steps, 1):
        t = (st.get("t") or "").strip()
        how = (st.get("how") or "").strip()
        pf = (st.get("preuve_fichier") or "")
        pf = pf.strip() if isinstance(pf, str) else ""
        chemin_attendu = _extraire_chemin(pf)
        etat, preuve, source = "inconnu", "", ""

        # 1) COMMIT post-go qui matche ce step. Matching STRICT (>=2 mots dont au moins
        #    un SPECIFIQUE) : un commit generique du projet ne doit jamais prouver un step.
        cm = next((c for c in commits
                   if _commit_matche_step(c.get("message", ""), t, how)),
                  None)
        if cm:
            etat, preuve, source = "fait", f"commit {cm['hash'][:7]}", "commit"

        # 2) FICHIER dur attendu par le step (radar preuve_fichier) posterieur au go.
        if etat == "inconnu" and chemin_attendu:
            iso = _fichier_dur(projet_dir, chemin_attendu, date_lancement)
            if iso:
                etat, preuve, source = "fait", chemin_attendu, "fichier"

        # 3/4) DIGEST : ligne(s) [step i] explicite(s), sinon ligne libre par similarite.
        if etat == "inconnu" and digest:
            candidats = list(dfait_n.get(i) or [])   # peut y en avoir plusieurs
            if not candidats:
                ref = _mots(t) | _mots(how)
                def _match_libre(l):
                    communs = ref & _mots(l["desc"])
                    return len(communs) >= 2 and any(m not in _STOP_STEP for m in communs)
                lib = next((l for l in dfait_libres if _match_libre(l)), None)
                if lib:
                    candidats = [lib]
            # Parmi les lignes du step, on privilegie celle qui porte une preuve DURE
            # (fichier reel post-go) ; a defaut la 1ere (temoignage attribue).
            choisi, chemin_dur = None, ""
            for d in candidats:
                ch = _extraire_chemin(d["preuve"])
                iso = _fichier_dur(projet_dir, ch, date_lancement) if ch else ""
                if iso:
                    choisi, chemin_dur = d, ch
                    break
            if choisi is None and candidats:
                choisi = candidats[0]
            if choisi is not None:
                if chemin_dur:   # le digest a POINTE une preuve dure -> fait systeme (trace digest)
                    etat, preuve, source = "fait", chemin_dur, "digest_fichier"
                else:            # action externe / non verifiable -> parole attribuee
                    etat, preuve, source = "fait", choisi["desc"], "digest"

        # 5) RESTE explicite du digest pour ce step.
        if etat == "inconnu" and digest and i in dreste_n:
            etat, preuve, source = "reste", dreste_n[i]["desc"], "digest"

        res.append({"n": i, "titre": t or how, "etat": etat,
                    "preuve": preuve, "source": source})
    return res


def _etape_couverte(etape: str, mots_faits: set) -> bool:
    """True si une etape clarifiee du do_now recouvre un step DEJA PROUVE fait, pour ne
    pas la re-lister sous 'Reste'. 'mots_faits' est un ensemble de frozensets de mots-cles
    (un par step prouve). Prudent (anti-suppression a tort) : on n'exclut que si >=2
    mots-cles significatifs de l'etape se retrouvent dans le titre d'un step prouve (memes
    briques _mots/_STOP que le reste du module). Peu de mots communs -> on GARDE l'etape
    (on prefere sur-lister un reste que masquer a tort une action non faite)."""
    mots_etape = _mots(etape)
    if len(mots_etape) < 2:
        return False
    for titre_mots in mots_faits:
        if len(mots_etape & titre_mots) >= 2:
            return True
    return False


# ------------------------------------------------------------------------------
# Reformulation CLAIRE du "Reste" (do_now) — 100% deterministe, ZERO token.
#   On CLARIFIE le do_now existant : on ne lui AJOUTE aucune etape, on n'en
#   retire aucune, on n'affirme JAMAIS qu'un bout est fait. Le "pourquoi" est
#   CITE depuis le move (pourquoi_maintenant/meta), jamais genere.
# ------------------------------------------------------------------------------

# Glossaire FERME : sigle connu -> version explicitee. Un sigle absent d'ici
# n'est JAMAIS devine. Cle en minuscule, match sur mot entier, casse-insensible.
_GLOSSAIRE = {
    "aeo":    "AEO (te rendre visible dans les reponses des IA)",
    "geo":    "GEO (etre cite par les moteurs generatifs)",
    "pr":     "PR (pull request)",
    "repo":   "repo (depot de code)",
    "dm":     "DM (message direct)",
    "readme": "README (la page d'accueil du repo)",
    "cta":    "CTA (bouton ou phrase d'appel a l'action)",
}

# URL github : owner/repo, avec ou sans schema/host, et forme "repo (github.com/owner)".
_RE_GH_FULL = re.compile(
    r"(?:https?://)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?", re.I)
# repo lisible cite AVANT son (github.com/owner) : 'visual-engine-optimization (github.com/alan-g-friar)'
_RE_GH_INLINE = re.compile(
    r"([A-Za-z0-9_.-]+)\s*\((?:https?://)?github\.com/([A-Za-z0-9_.-]+)\)", re.I)
# owner/repo nu (pas d'espace, un seul slash, pas une URL http) — ex 'jamesleoreyes/cc-usage-tracker-tracker'
_RE_OWNER_REPO = re.compile(r"(?<![\w/])([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]{2,})(?![\w/])")
# toute autre URL http(s)
_RE_URL = re.compile(r"https?://([A-Za-z0-9.-]+)(?:/\S*)?", re.I)


def _nettoyer_urls(txt: str) -> str:
    """Remplace les URLs/refs github par des noms lisibles. N'INVENTE rien :
    ne fait que reecrire ce qui est deja ecrit (owner/repo/domaine reels).

    Amelioration 2 : un repo cite via github.com dans un do_now est un repo EXTERNE sur
    GitHub, a CONSULTER (pas le code d'Adam). On le nomme donc explicitement 'le repo
    GitHub X (de owner)' pour lever l'ambiguite ('le repo X' laissait croire qu'on ouvre
    SON projet). Le mot 'GitHub' n'est ajoute QUE quand la source contenait 'github.com'
    (donc factuel, jamais devine) ; owner/repo reels intacts, aucune etape ajoutee. Un
    owner/repo NU (sans github.com) reste 'le repo X (de owner)' : on n'affirme pas GitHub
    la ou le do_now ne l'a pas ecrit."""
    def repo(owner, name):
        return f"le repo {name} (de {owner})"

    def repo_github(owner, name):
        # 'github.com' etait dans la source -> on peut le dire (factuel + mot deja present).
        return f"le repo GitHub {name} (de {owner})"

    # 1) 'repo (github.com/owner)' -> 'le repo GitHub repo (de owner)'  [avant la forme full]
    txt = _RE_GH_INLINE.sub(lambda m: repo_github(m.group(2), m.group(1)), txt)
    # 2) [https://]github.com/owner/repo -> 'le repo GitHub repo (de owner)'
    txt = _RE_GH_FULL.sub(lambda m: repo_github(m.group(1), m.group(2)), txt)
    # 3) autres URLs http(s) -> 'la page <domaine>'
    txt = _RE_URL.sub(lambda m: f"la page {m.group(1)}", txt)
    # 4) owner/repo nu residuel -> 'le repo repo (de owner)' (sans 'GitHub' : non ecrit dans
    #    la source). On evite de casser les vrais chemins de fichier a extension connue.
    def _or(m):
        owner, name = m.group(1), m.group(2)
        # Garde chemin-de-fichier : on strippe la ponctuation finale AVANT de lire
        # l'extension, sinon 'index.html.' (phrase finissant par le fichier + point)
        # donne ext='' et serait pris a tort pour un repo. Extensions connues elargies.
        name_net = name.rstrip(".,;:!?)")
        ext = name_net.rsplit(".", 1)[-1].lower() if "." in name_net else ""
        if ext in ("py", "md", "markdown", "js", "ts", "jsx", "tsx", "json",
                   "html", "htm", "css", "scss", "txt", "yml", "yaml", "toml",
                   "png", "jpg", "svg", "webp", "mp4", "sh", "bat", "ps1"):
            return m.group(0)  # c'est un chemin de fichier, on laisse tel quel
        return repo(owner, name)
    txt = _RE_OWNER_REPO.sub(_or, txt)
    return txt


def _expliciter_sigles(txt: str) -> str:
    """Explicite chaque sigle CONNU une seule fois (au 1er passage), en respectant
    les limites de mots. Un sigle hors glossaire est laisse tel quel (jamais devine)."""
    fait = set()
    def sub(m):
        mot = m.group(0)
        cle = mot.lower()
        if cle in _GLOSSAIRE and cle not in fait:
            fait.add(cle)
            return _GLOSSAIRE[cle]
        return mot
    # \b sur mots alphanum ; on ne touche pas au texte deja injecte (les remplacements
    # contiennent des parentheses/minuscules qui ne re-matchent pas les cles seules).
    return re.sub(r"\b[A-Za-z]{2,7}\b", sub, txt)


def _decouper_do_now(txt: str, max_morceaux: int = 2) -> list:
    """Coupe le do_now en 1-2 etapes sur un separateur d'ACTION, sans reordonner,
    fusionner ni supprimer. Garde tout : le residu au-dela de 2 morceaux est
    rattache au 2e (rien n'est perdu = rien n'est masque)."""
    seps = (" puis ", " et note ", " note ", " — ", " - ")
    reste = txt.strip()
    morceaux = []
    while reste and len(morceaux) < max_morceaux - 1:
        idx, sep_len = None, 0
        for sep in seps:
            i = reste.lower().find(sep)
            if i > 8 and (idx is None or i < idx):
                idx, sep_len = i, len(sep)
        if idx is None:
            break
        morceaux.append(reste[:idx].strip(" -—,;:"))
        reste = reste[idx + sep_len:].strip(" -—,;:")
    if reste:
        morceaux.append(reste.strip(" -—,;:"))
    return [m for m in morceaux if m]


def _reste_clair(do_now: str, entree: dict) -> list:
    """CLARIFIE le do_now en 1-2 etapes lisibles. Renvoie une LISTE de lignes de
    texte BRUT (l'appelant echappe + met en forme). Aucune etape ajoutee/retiree ;
    le do_now tronque garde ses '...'. Le 'pourquoi' est CITE depuis le move,
    jamais genere. [] si do_now vide."""
    d = (do_now or "").strip()
    if not d:
        return []
    # Sigles AVANT nettoyage d'URL : sinon le mot "repo" injecte par la reecriture
    # d'URL ('le repo X (de owner)') se ferait re-expliciter en 'repo (depot de code)'
    # -> 'le repo (depot de code) X', illisible. On explicite donc les sigles du
    # do_now brut, puis on reecrit les URLs (qui posent leur propre 'repo' propre).
    d = _nettoyer_urls(_expliciter_sigles(d))
    morceaux = [_troncature_move(m, 150) for m in (_decouper_do_now(d) or [d])]
    # Le 'pourquoi' est CITE depuis le vrai champ du radar (jamais 'meta' qui est un
    # tag d'effort '1h - positionnement', trompeur sous ce label ; jamais genere).
    pourquoi = (entree.get("pourquoi_maintenant") or "").strip()
    if pourquoi:
        morceaux.append("pourquoi : " + _troncature_move(pourquoi, 120))
    return morceaux


def _detail_en_cours(entree: dict) -> str:
    """DETAIL riche & FACTUEL 'ou on en est' d'un go actif (en_cours / projet_bouge),
    en HTML Telegram, sous 3 rubriques :

      • FAIT     : les commits reels depuis le go (heure + resume du message).
      • EN COURS : les fichiers modifies non commites (nommes, dates en relatif).
      • RESTE    : deduit du do_now du move MOINS ce qui est deja prouve. Si on ne peut
                   pas savoir, on renvoie au move ('cf le move: ...') plutot que d'affirmer.

    RÈGLE DURE : chaque ligne s'appuie sur un commit reel OU un fichier reel de l'etat.
    Aucune etape n'est declaree faite sans preuve. Zero LLM, zero invention.

    Renvoie '' si le go n'est ni 'en_cours' ni 'projet_bouge' (pas de detail a montrer)."""
    if entree.get("statut") not in ("en_cours", "projet_bouge"):
        return ""

    projet_dir = entree.get("projet_dir", "")
    date_lancement = entree.get("date_lancement", "")
    do_now = (entree.get("do_now") or "").strip()

    # Commits reels depuis le go (memes que _decider ; recalcules ici pour autonomie).
    commits = entree.get("_commits")
    if commits is None:
        commits = _git_commits_apres(projet_dir, date_lancement)
    # Fichiers non commites reels (relus du git status).
    fichiers = _fichiers_non_commites(projet_dir)

    lignes = []

    # --- FAIT : commits reels ---
    if commits:
        lignes.append("<b>Fait</b>")
        # plus recent d'abord (git log l'est deja), max 4 pour rester lisible sur Telegram
        for c in commits[:4]:
            h = _heure_locale(c.get("date", ""))
            resume = _safe_html(_resume_commit(c.get("message", "")))
            when = f" — {h}" if h else ""
            lignes.append(f"  ✓ {resume}{when}")
        if len(commits) > 4:
            lignes.append(f"  <i>+ {len(commits) - 4} autre(s) commit(s)</i>")

    # --- EN COURS : fichiers non commites reels ---
    if fichiers:
        lignes.append("<b>En cours</b>")
        phrase = _safe_html(_regrouper_fichiers(fichiers))
        lignes.append(f"  ✎ {phrase}")

    # --- CE QUE CE GO A PRODUIT : steps du plan mappes a leur preuve (dure d'abord,
    #     digest CITE en complement). Rendu uniquement si le go porte des steps figes.
    digest = _lire_digest(projet_dir, date_lancement)
    steps = entree.get("steps") or []
    steps_faits_mots = set()   # mots-cles des steps prouves faits -> retires du "Reste"
    if steps:
        appariement = _apparier_steps(steps, commits, digest, projet_dir, date_lancement)
        faits = [a for a in appariement if a["etat"] == "fait"]
        if faits:
            entete = "<b>Ce que ce go a produit</b>"
            if digest and digest.get("statut"):
                entete += f" <i>(Claude Code dit : {_safe_html(digest['statut'])})</i>"
            lignes.append(entete)
            for a in faits:
                steps_faits_mots.add(frozenset(_mots(a["titre"])))
                titre = _safe_html(_troncature_move(a["titre"], 90))
                if a["source"] in ("commit", "fichier", "digest_fichier"):
                    if a["source"] == "commit":
                        tag = f"✔ {_safe_html(a['preuve'])}"
                    else:
                        tag = f"✔ {_safe_html(a['preuve'])} — fichier présent"
                    lignes.append(f"  ✓ {titre}  ·  {tag}")
                else:   # source == digest : action externe, JAMAIS un fait systeme -> cite
                    detail = _safe_html(_troncature_move(a["preuve"] or a["titre"], 70))
                    lignes.append(f"  ✓ {titre}  ·  <i>d'après Claude Code ({detail})</i>")
        # RESTE dit explicitement par le digest (attribue, jamais fusionne en fait).
        if digest:
            for a in [a for a in appariement if a["etat"] == "reste"]:
                r = _safe_html(_troncature_move(a["preuve"] or a["titre"], 90))
                lignes.append(f"  ↔ <i>Reste (dit par Claude Code) : {r}</i>")

    # OBSERVE du digest : ce que Claude Code a AUDITE sans produire de fichier. TOUJOURS
    # cite comme temoignage ("d'apres Claude Code"), JAMAIS promu en fait systeme (pas de
    # coche ✓, pas de preuve dure) — c'est justement une etape sans artefact. Rendu meme
    # sans steps mappes, car il ne depend d'aucun appariement de plan.
    if digest:
        for o in digest.get("observe", [])[:3]:
            libelle = o.get("desc") or ""
            note_o = o.get("preuve") or ""
            if not libelle:
                continue
            texte = f"{libelle} ({note_o})" if note_o else libelle
            lignes.append(f"  👁 <i>Observé (d'après Claude Code) : "
                          f"{_safe_html(_troncature_move(texte, 90))}</i>")

    # Liens + note du digest (attribues), meme sans steps mappes.
    if digest:
        for l in digest.get("liens", [])[:3]:
            cible = l.get("preuve") or l.get("desc") or ""
            if cible:
                lignes.append(f"  🔗 {_safe_html(_troncature_move(cible, 80))}")
        if digest.get("note"):
            note = _safe_html(_troncature_move(digest["note"], 140))
            lignes.append(f"  <i>— Note (Claude Code) : {note}</i>")

    # --- RESTE : on CLARIFIE le do_now (jamais on ne juge l'avancement). On NE repete
    #     PAS une etape deja prouvee faite ci-dessus (do_now vidé de ces bribes si besoin).
    if do_now:
        morceaux = _reste_clair(do_now, entree)
        etapes = [m for m in morceaux if not m.startswith("pourquoi : ")]
        pourquois = [m for m in morceaux if m.startswith("pourquoi : ")]
        # Filtre : une etape du do_now qui recouvre un step deja prouve fait n'est pas
        # re-listee comme "reste" (elle est faite, prouve ci-dessus).
        if steps_faits_mots:
            etapes = [m for m in etapes if not _etape_couverte(m, steps_faits_mots)]
        morceaux = etapes + pourquois
        # S'il ne reste que le 'pourquoi' (toutes les etapes sont faites), on n'affiche
        # pas un "Reste" vide trompeur.
        if etapes:
            lignes.append("<b>Reste</b>")
            lignes.append("  → Il te reste a :")
            for m in morceaux:
                txt = _safe_html(m)
                if m.startswith("pourquoi : "):
                    lignes.append(f"     <i>— {txt}</i>")
                elif len(etapes) > 1:
                    lignes.append(f"     • {txt}")
                else:
                    lignes.append(f"     {txt}")

    # --- OU ATTERRIT TON TRAVAIL (Amelioration 3) : fait rassurant, pas une supposition.
    #     Le projet_dir est reel ; on nomme le produit + le dossier technique quand connu.
    produit = _nom_affichage(entree.get("projet", ""))
    dossier = _nom_dossier_technique(entree)
    if dossier and _norm(produit) != _norm(dossier):
        lignes.append(f"📂 Ton travail va dans : <b>{_safe_html(produit)}</b> "
                      f"(dossier {_safe_html(dossier)})")
    elif produit and produit != "?":
        lignes.append(f"📂 Ton travail va dans : <b>{_safe_html(produit)}</b>")

    return "\n".join(lignes)


# ------------------------------------------------------------------------------
# Decision du statut (hierarchie stricte) — ETAGES 0 et 1, ZERO token
# ------------------------------------------------------------------------------

STATUTS = ("lance", "en_cours", "projet_bouge", "probablement_fait",
           "fait", "paye", "dormant", "dormant_archive", "skip")


def _decider(entree: dict) -> dict:
    """Applique la hierarchie sur une entree en construction. Mute + renvoie l'entree.
    N'utilise QUE des faits (events, confirmations, commits dates). Pas de LLM ici."""
    cle = entree["cle"]
    move = entree["_move"]
    projet_radar = entree["projet"]
    date_lancement = entree["date_lancement"]

    preuves = [{"type": "lancement", "detail": "go traite",
                "source": "data/go_traites.json", "date": date_lancement}]

    # --- Confirmations directes d'Adam (autorite supreme) ---
    conf = entree["_confirmations"].get(cle)

    # --- Events feedback lies au projet, POSTERIEURS au lancement ---
    pn = _norm(projet_radar)
    ev_projet = [e for e in entree["_events"]
                 if _norm(e.get("projet", "")) == pn
                 and (not e.get("date") or not _parse_date(date_lancement)
                      or not _apres(date_lancement, e.get("date", "")))]
    paye_ev = next((e for e in ev_projet if (e.get("type") or "").lower() == "paye"), None)
    fait_ev = next((e for e in ev_projet if (e.get("type") or "").lower() == "fait"), None)

    # --- Commits git dates, posterieurs au lancement (etage 1) ---
    commits = _git_commits_apres(entree.get("projet_dir", ""), date_lancement)
    entree["commits_depuis_go"] = len(commits)
    commit_preuve = next((c for c in commits if _commit_matche_move(c["message"], move)), None)

    statut = "lance"
    montant = None

    if conf and conf.get("quoi") == "paye":
        statut, montant = "paye", conf.get("montant")
        preuves.append({"type": "confirmation_adam", "detail": f"paye {montant}",
                        "source": "go_confirmations.jsonl", "date": conf.get("date")})
    elif paye_ev:
        statut, montant = "paye", paye_ev.get("montant")
        preuves.append({"type": "event_feedback", "detail": f"paye {montant}",
                        "source": "feedback_events.jsonl", "date": paye_ev.get("date")})
    elif conf and conf.get("quoi") == "fait":
        statut = "fait"
        preuves.append({"type": "confirmation_adam", "detail": "fait",
                        "source": "go_confirmations.jsonl", "date": conf.get("date")})
    elif fait_ev:
        statut = "fait"
        preuves.append({"type": "event_feedback", "detail": "fait",
                        "source": "feedback_events.jsonl", "date": fait_ev.get("date")})
    elif commit_preuve:
        statut = "fait"
        preuves.append({"type": "commit", "detail": f"\"{commit_preuve['message'][:60]}\"",
                        "source": "git", "date": commit_preuve["date"]})
    elif conf and conf.get("quoi") == "skip":
        statut = "skip"
        preuves.append({"type": "confirmation_adam", "detail": "skip",
                        "source": "go_confirmations.jsonl", "date": conf.get("date")})
    elif commits:
        statut = "projet_bouge"   # le PROJET a bouge (prouve) ; ne dit PAS que le move est fait
        preuves.append({"type": "commit", "detail": f"{len(commits)} commit(s) depuis le go",
                        "source": "git", "date": commits[0]["date"]})
    else:
        # Pas de commit : le projet BOUGE-T-IL quand meme ? (session ouverte, travail non
        # committe, fichiers modifies). C'est ce qui repond a "ca bosse mais ca dit rien".
        travail = _travail_en_cours(entree.get("projet_dir", ""), date_lancement)
        if travail["en_cours"]:
            statut = "en_cours"
            preuves.append({"type": "travail", "detail": travail["detail"],
                            "source": "git status / fichiers", "date": travail["date"]})
        elif _jours_depuis(date_lancement) > JOURS_ARCHIVE:
            # ARCHIVAGE (dette P2) : > 21 jours sans la MOINDRE preuve (ni confirmation,
            # ni event, ni commit, ni travail en cours) -> le go sort de l'affichage
            # quotidien (c'est du bruit) mais reste ENTIER dans go_suivi.json et est
            # compte dans le statut complet. Fait dur (dates reelles comparees), pas
            # une supposition — et JAMAIS une suppression de donnees.
            statut = "dormant_archive"
        elif _jours_depuis(date_lancement) >= JOURS_DORMANT:
            statut = "dormant"    # >=5j sans le moindre mouvement = fait dur, pas une supposition

    entree["statut"] = statut
    entree["montant"] = montant
    entree["confiance"] = 1.0     # etages 0-1 : purement factuel
    entree["preuves"] = preuves
    entree.setdefault("hypotheses", [])
    entree["confirme_par_adam"] = conf or None
    entree["_commits"] = commits   # garde pour un eventuel etage 2 (non serialise)
    return entree


# ------------------------------------------------------------------------------
# rafraichir() : reconstruit go_suivi.json (idempotent, deterministe, 0 token)
# ------------------------------------------------------------------------------

def rafraichir() -> dict:
    go_traites = _load(GO_TRAITES, []) or []
    horodatage = _load(HORODATAGE, {}) or {}
    snapshots = _load(SNAPSHOTS, {}) or {}
    radars = _radars_par_date()
    events = _events_feedback()
    confs = _confirmations()

    entrees = []
    for cle in go_traites:
        if "|" not in str(cle):
            continue
        date_radar, move_id = str(cle).split("|", 1)

        # SOURCE DU MOVE, par ordre d'autorite :
        #   1. le SNAPSHOT fige au moment du go (auto-portant, immunise contre la
        #      regeneration du radar) -> c'est LUI qui empeche les go orphelins ;
        #   2. a defaut (go legacy sans snapshot), le radar de date_radar via le _id.
        snap = snapshots.get(cle) or {}
        radar = radars.get(date_radar)
        move_radar = _move_par_id(radar, move_id) or {}
        move = snap or move_radar

        projet_radar = snap.get("projet") or move_radar.get("projet", "")
        projet_dir = snap.get("projet_dir") or ""
        if not projet_dir and projet_radar:
            projet_dir, _err = resoudre_dossier(projet_radar)
            projet_dir = projet_dir or ""

        # Date de lancement : le snapshot la porte deja (instant reel) ; sinon l'horodatage ;
        # sinon repli sur la date du radar. Ancrer sur l'instant reel elimine le faux positif
        # "commit du matin" : un commit anterieur a TA reponse 'go' ne compte pas.
        date_lancement = snap.get("date_lancement") or horodatage.get(cle) or date_radar

        # PLAN (steps) pour mapper "ce que ce go a produit" : d'abord le snapshot fige (source
        # auto-portante), sinon RATTRAPAGE best-effort depuis le radar de date_radar via le
        # _id. [] si le radar a change (go legacy sans steps figes) -> la rubrique se masque
        # proprement, aucune regression.
        steps = snap.get("steps")
        if steps is None:
            steps = move_radar.get("steps", []) or []

        entree = {
            "cle": cle, "move_id": move_id, "date_radar": date_radar,
            "projet": projet_radar, "projet_dir": projet_dir,
            "move_title": move.get("title", ""), "do_now": move.get("do_now", ""),
            "meta": move.get("meta", ""),
            "steps": steps,
            # le VRAI 'pourquoi' du radar (pas 'meta' qui est un tag d'effort '1h - ...').
            # Cite tel quel par _reste_clair, jamais genere.
            "pourquoi_maintenant": move.get("pourquoi_maintenant", ""),
            "date_lancement": date_lancement,
            "dernier_check": _now().isoformat(),
            # champs internes (non serialises) pour _decider :
            "_move": move, "_events": events, "_confirmations": confs,
        }
        _decider(entree)
        # purge des champs internes avant serialisation
        for k in ("_move", "_events", "_confirmations", "_commits"):
            entree.pop(k, None)
        entrees.append(entree)

    snap = {"version": 1, "genere_le": _now().isoformat(), "go": entrees}
    DATA.mkdir(parents=True, exist_ok=True)
    write_json_atomic(OUT, snap)
    return snap


# ------------------------------------------------------------------------------
# ETAGE 2 : LLM Opus, RARE et a la demande (jamais en boucle auto)
# ------------------------------------------------------------------------------

def _claude_env() -> dict:
    """Env propre pour 'claude -p' appele depuis une session Claude (evite les
    variables qui casseraient l'auth headless)."""
    env = dict(os.environ)
    for k in ("ANTHROPIC_BASE_URL", "CLAUDE_CODE_SESSION_ID", "ANTHROPIC_API_KEY",
              "CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE"):
        env.pop(k, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _preuve_est_reelle(preuve_citee: str, commits: list) -> bool:
    """Anti-invention : l'hypothese LLM n'est gardee que si sa preuve reprend un
    fragment reel (>=5 lettres consecutives) d'un message de commit reellement fourni."""
    pc = (preuve_citee or "").lower()
    if len(pc) < 5:
        return False
    for c in commits:
        msg = c.get("message", "").lower()
        # cherche un mot du commit (>=5 lettres) present dans la preuve citee
        for mot in re.findall(r"[a-z]{5,}", msg):
            if mot in pc:
                return True
    return False


def inferer_llm(cle: str, force: bool = False) -> dict:
    """Etage 2, EXPLICITE. Sur un go 'projet_bouge' (le projet a bouge mais aucun
    commit ne matche le move), on demande a Opus si le move a l'air fait. Verdict
    plafonne a 'probablement_fait', ecrit en HYPOTHESE (jamais en preuve, jamais 'paye').
    Retourne {ok, raison?, hypothese?}."""
    snap = _load(OUT, None) or rafraichir()
    entree = next((g for g in snap["go"] if g["cle"] == cle), None)
    if not entree:
        return {"ok": False, "raison": "cle inconnue"}
    if entree["statut"] != "projet_bouge":
        return {"ok": False, "raison": f"statut '{entree['statut']}' : pas de cas ambigu a lever"}

    # rate-limit 24h par go (sauf --force)
    dernier = entree.get("llm_dernier_appel")
    if dernier and not force and _jours_depuis(dernier) < (LLM_RATE_LIMIT_H / 24.0):
        return {"ok": False, "raison": "deja interroge il y a <24h"}

    commits = _git_commits_apres(entree.get("projet_dir", ""), entree["date_lancement"])
    if not commits:
        return {"ok": False, "raison": "aucun commit a analyser"}

    liste = "\n".join(f"- {c['date'][:10]} {c['message']}" for c in commits[:LLM_COMMITS_MAX])
    prompt = (
        "Tu verifies si un MOVE precis a ete realise, en te basant UNIQUEMENT sur des "
        "commits git reels. N'invente rien. Reponds en JSON strict.\n\n"
        f"MOVE : {entree['move_title']}\n"
        f"ACTION ATTENDUE : {entree['do_now']}\n\n"
        f"COMMITS RECENTS DU PROJET (apres le lancement du move) :\n{liste}\n\n"
        "Question : ces commits montrent-ils que CE move a ete realise ?\n"
        'Reponds STRICTEMENT : {"verdict":"probablement_fait|projet_bouge",'
        '"confiance":0.0-1.0,"preuve_citee":"<fragment exact d\'un commit ci-dessus>"}\n'
        "Regles : verdict 'probablement_fait' seulement si un commit correspond vraiment "
        "au move. Sinon 'projet_bouge'. 'preuve_citee' DOIT etre un extrait litteral d'un "
        "commit liste. Tu ne peux PAS conclure a une vente ou un paiement."
    )
    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", "opus", "--output-format", "text", prompt],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace", env=_claude_env(),
        )
        brut = (proc.stdout or "").strip()
    except Exception as e:
        return {"ok": False, "raison": f"appel claude KO: {e!r}"}

    m = re.search(r"\{.*\}", brut, re.DOTALL)
    if not m:
        _marquer_llm(cle)
        return {"ok": False, "raison": "reponse LLM non parsable"}
    try:
        verdict = json.loads(m.group(0))
    except Exception:
        _marquer_llm(cle)
        return {"ok": False, "raison": "JSON LLM invalide"}

    v = str(verdict.get("verdict", "")).lower()
    conf = float(verdict.get("confiance", 0) or 0)
    preuve = str(verdict.get("preuve_citee", ""))

    # Garde-fous durs : 'paye'/'fait' interdits au LLM ; preuve doit etre reelle ; seuil.
    if v not in ("probablement_fait", "projet_bouge"):
        _marquer_llm(cle)
        return {"ok": False, "raison": f"verdict LLM refuse: {v!r}"}
    if v == "probablement_fait" and (conf < LLM_CONF_MIN or not _preuve_est_reelle(preuve, commits)):
        v, conf = "projet_bouge", min(conf, 0.5)

    hypothese = {"source": "llm_opus", "verdict": v, "confiance": round(conf, 2),
                 "preuve_citee": preuve, "date": _now().isoformat()}
    _appliquer_hypothese(cle, hypothese)
    return {"ok": True, "hypothese": hypothese}


def _marquer_llm(cle: str) -> None:
    snap = _load(OUT, None)
    if not snap:
        return
    for g in snap["go"]:
        if g["cle"] == cle:
            g["llm_dernier_appel"] = _now().isoformat()
    write_json_atomic(OUT, snap)


def _appliquer_hypothese(cle: str, hypothese: dict) -> None:
    """Ecrit l'hypothese LLM DANS hypotheses[] (jamais preuves[]). Le statut ne monte
    a 'probablement_fait' que si le verdict le dit ET que le statut factuel etait
    'projet_bouge' (le LLM ne peut jamais degrader une preuve dure)."""
    snap = _load(OUT, None)
    if not snap:
        return
    for g in snap["go"]:
        if g["cle"] != cle:
            continue
        g.setdefault("hypotheses", []).append(hypothese)
        g["llm_dernier_appel"] = _now().isoformat()
        if g["statut"] == "projet_bouge" and hypothese["verdict"] == "probablement_fait":
            g["statut"] = "probablement_fait"
            g["confiance"] = hypothese["confiance"]   # <1.0 : c'est une hypothese
    write_json_atomic(OUT, snap)


# ------------------------------------------------------------------------------
# Confirmations d'Adam (fait / skip / paye)
# ------------------------------------------------------------------------------

def cle_du_go_numero(n: int) -> str:
    """Traduit 'fait 2' -> la cle du 2e go actif (ordre d'affichage du radar/statut).
    Retourne '' si hors bornes."""
    snap = _load(OUT, None) or rafraichir()
    go = _go_affichage(snap)
    return go[n - 1]["cle"] if 1 <= n <= len(go) else ""


def enregistrer_confirmation(cle: str, quoi: str, montant: str = "", texte_brut: str = "") -> bool:
    """Append une confirmation d'Adam dans go_confirmations.jsonl (autorite supreme).
    quoi in {fait, paye, skip}. 'montant' n'est garde que pour 'paye'. Puis rafraichit."""
    if quoi not in ("fait", "paye", "skip") or not cle:
        return False
    rec = {"cle": cle, "quoi": quoi,
           "montant": montant if quoi == "paye" else "",
           "date": _now().isoformat(), "texte_brut": texte_brut}
    DATA.mkdir(parents=True, exist_ok=True)
    with CONFIRM.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # 'paye' alimente AUSSI l'apprentissage (feedback.py) : le signal ARGENT remonte.
    if quoi == "paye":
        _propager_paye_au_feedback(cle, montant)
    rafraichir()
    return True


def _propager_paye_au_feedback(cle: str, montant: str) -> None:
    """Quand Adam confirme 'paye', on log aussi l'event dans feedback.py (idempotent)
    pour que la couche d'apprentissage sache que ce type de signal a paye."""
    snap = _load(OUT, None)
    projet = ""
    for g in (snap or {}).get("go", []):
        if g["cle"] == cle:
            projet = g["projet"]
    if not projet:
        return
    try:
        import feedback  # type: ignore
        feedback.enregistrer_event("paye", projet, montant)
    except Exception:
        pass


# ------------------------------------------------------------------------------
# Formulation des insights (honnete sur la certitude, cite toujours sa preuve)
# ------------------------------------------------------------------------------

_ORDRE_ACTION = {"dormant": 0, "en_cours": 1, "projet_bouge": 2, "probablement_fait": 3,
                 "fait": 4, "lance": 5, "paye": 6, "skip": 7}


def _go_affichage(snap: dict) -> list:
    """Go a montrer, tries par urgence d'action (ce qui demande une decision d'abord).
    Les 'skip' sont exclus de l'affichage courant ; les 'dormant_archive' aussi
    (> 21j sans preuve = bruit au quotidien) — ils restent ENTIERS dans le snapshot
    et sont COMPTES par une ligne dediee du statut complet, jamais supprimes."""
    go = [g for g in snap.get("go", []) if g["statut"] not in ("skip", "dormant_archive")]
    go.sort(key=lambda g: _ORDRE_ACTION.get(g["statut"], 9))
    return go


def _numero(snap: dict, cle: str) -> int:
    for i, g in enumerate(_go_affichage(snap), 1):
        if g["cle"] == cle:
            return i
    return 0


def _quand(g: dict) -> str:
    j = int(_jours_depuis(g["date_lancement"]))
    return "aujourd'hui" if j <= 0 else ("hier" if j == 1 else f"il y a {j}j")


def _preuve_citee(g: dict) -> str:
    """La preuve la plus parlante, pour l'afficher (transparence totale)."""
    for p in reversed(g.get("preuves", [])):
        if p["type"] in ("commit", "event_feedback", "confirmation_adam", "travail"):
            d = (p.get("date") or "")[:10]
            return f"{p['detail']}" + (f" ({d})" if d else "")
    return ""


def _nom_affichage(projet: str) -> str:
    """Nom PRODUIT a afficher (ex 'BrandPulse') a partir du nom technique ('serp-scraper')
    ou de n'importe quel alias. Si inconnu, on renvoie le nom tel quel (jamais vide->'?').
    data/projets.json en priorite (audit Fable, reco #4) ; NOMS_AFFICHAGE fige en repli
    si le fichier est absent/corrompu ou que le projet n'y figure pas encore."""
    if not projet:
        return "?"
    if _cp is not None:
        idx = _cp.index_alias()
        slug = idx.get(str(projet).strip().lower())
        if slug:
            nom = _cp.nom_affichage_de(slug)
            if nom:
                return nom
    return NOMS_AFFICHAGE.get(_norm(projet), projet)


def _nom_dossier_technique(g: dict) -> str:
    """Nom TECHNIQUE du dossier du projet (ex 'serp-scraper'), FACTUEL : lu du basename
    du vrai projet_dir si present, sinon du champ 'projet' brut du move. '' si aucun des
    deux. Aucune invention : on ne renvoie que ce qui est deja ecrit/present sur disque."""
    projet_dir = (g.get("projet_dir") or "").strip()
    if projet_dir:
        base = Path(projet_dir).name
        if base:
            return base
    return (g.get("projet") or "").strip()


def _mention_dossier(g: dict) -> str:
    """Renvoie ' <i>(dossier serp-scraper)</i>' quand le nom PRODUIT affiche differe du nom
    TECHNIQUE du dossier, pour lever l'ambiguite une seule fois. '' si identiques (comparaison
    normalisee via _norm) ou si le dossier technique est inconnu. FACTUEL : le dossier vient
    du vrai projet_dir/champ projet, jamais devine."""
    produit = _nom_affichage(g.get("projet", ""))
    dossier = _nom_dossier_technique(g)
    if not dossier or _norm(produit) == _norm(dossier):
        return ""
    return f" <i>(dossier {_safe_html(dossier)})</i>"


def _insight(g: dict, num: int) -> str:
    """Une ligne HTML : etat + projet + ce que ca veut dire + quoi faire. Formule net."""
    s, proj = g["statut"], _nom_affichage(g["projet"])
    # Nom produit + (dossier technique) une seule fois quand ils different (Amelioration 1).
    tete = f"<b>{num}. {proj}</b>{_mention_dossier(g)}"
    # Registre accentue partout (jury produit, vague 2B) : le reste du radar est
    # en francais correct, cette section ne doit pas rompre le ton chaque matin.
    if s == "paye":
        m = f" ({g['montant']})" if g.get("montant") else ""
        return f"💶 {tete} — <b>a payé{m}</b>. Tu l'as confirmé. Ce type de move rapporte : refais-en."
    if s == "fait":
        pr = _preuve_citee(g)
        pr = f" <i>[{pr}]</i>" if pr else ""
        return f"✅ {tete} — <b>fait</b>, shippé.{pr} À monétiser si ce n'est pas déjà le cas."
    if s == "probablement_fait":
        h = next((x for x in reversed(g.get("hypotheses", [])) if x.get("verdict") == "probablement_fait"), {})
        pr = h.get("preuve_citee", "")
        return (f"🟡 {tete} — <b>probablement fait</b> (hypothèse, {int(g.get('confiance',0)*100)}%). "
                f"Indice : « {_safe_html(pr)[:50]} ». Confirme avec « fait {num} » si c'est bon.")
    if s == "en_cours":
        return (f"🛠️ {tete} — <b>tu bosses dessus</b>, lancé {_quand(g)}. "
                f"Pas encore de commit figé. Continue, ou dis « fait {num} » quand c'est shippé.")
    if s == "projet_bouge":
        return (f"🔨 {tete} — <b>ça avance</b>, lancé {_quand(g)}, le projet bouge "
                f"({g.get('commits_depuis_go',0)} commit(s)) mais rien qui prouve ce move précis. "
                f"Termine-le, ou dis « fait {num} ».")
    if s == "dormant":
        return (f"💤 {tete} — <b>dormant</b> : lancé {_quand(g)}, zéro mouvement depuis. "
                f"À relancer, ou classe-le avec « skip {num} ».")
    return f"🚀 {tete} — <b>lancé {_quand(g)}</b>, encore aucun signe. Normal si c'est frais."


def _safe_html(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _fait_recent_court(g: dict) -> str:
    """UNE ligne courte nommant le FAIT le plus recent d'un go actif, pour le radar
    matinal (pas le detail complet). Priorite au dernier commit (nomme + heure) ; a
    defaut au fichier non commite le plus recent (nomme + horloge relative). '' sinon.
    100% factuel : que du reel (commits git / git status), zero invention."""
    if g.get("statut") not in ("en_cours", "projet_bouge"):
        return ""
    projet_dir = g.get("projet_dir", "")
    # dernier commit reel depuis le go (le plus recent d'abord dans git log)
    commits = g.get("_commits")
    if commits is None:
        commits = _git_commits_apres(projet_dir, g.get("date_lancement", ""))
    if commits:
        c = commits[0]
        h = _heure_locale(c.get("date", ""))
        resume = _safe_html(_resume_commit(c.get("message", "")))
        when = f" ({h})" if h else ""
        return f"   ↳ dernier : <i>{resume}</i>{when}"
    # sinon, le fichier non commite le plus recent
    fichiers = _fichiers_non_commites(projet_dir)
    if fichiers:
        recent = max(fichiers, key=lambda f: f.get("mtime") or "")
        nom = _safe_html(_nom_court(recent["fichier"]))
        horloge = _il_y_a(recent.get("mtime", ""))
        when = f" ({horloge})" if horloge else ""
        return f"   ↳ en cours : <i>{nom}</i>{when}"
    return ""


def formater_section_radar(max_go: int = 4) -> str:
    """Section courte 'Tes go en cours' pour le bas du radar matinal (HTML Telegram).
    '' si aucun go actif (le radar ne s'alourdit pas pour rien).
    Chaque go actif = son insight (1 ligne) + le fait le plus recent nomme (1 ligne),
    soit 1-2 lignes max ; JAMAIS le detail complet Fait/En cours/Reste (reserve a 'statut')."""
    snap = rafraichir()
    go = _go_affichage(snap)
    if not go:
        return ""
    L = ["", "━━━━━━━━━━━━━━━", "📌 <b>Tes go en cours</b>"]
    for i, g in enumerate(go[:max_go], 1):
        L.append(_insight(g, i))
        recent = _fait_recent_court(g)   # 2e ligne courte : le fait le plus recent nomme
        if recent:
            L.append(recent)
    reste = len(go) - max_go
    if reste > 0:
        L.append(f"<i>+ {reste} autre(s). Ecris « statut » pour tout voir.</i>")
    return "\n".join(L)


def formater_statut_complet() -> str:
    """Detail complet pour la commande Telegram 'statut' (HTML). Pied honnete si rien.
    Les go archives (dormant_archive, > 21j sans preuve) ne sont plus detailles ligne
    a ligne : une ligne dediee les COMPTE — ils restent entiers dans go_suivi.json,
    l'archivage n'est JAMAIS une suppression."""
    snap = rafraichir()
    go = _go_affichage(snap)
    archives = [g for g in snap.get("go", []) if g.get("statut") == "dormant_archive"]
    if not go and not archives:
        return ("📌 <b>Suivi des go</b>\n\n"
                "<i>Aucun go en cours. Reponds « go N » a un radar pour en lancer un.</i>")
    L = ["📌 <b>Suivi de tes go</b> — <i>prouve, sans invention</i>", "━━━━━━━━━━━━━━━"]
    if not go:
        L.append("")
        L.append("<i>Aucun go actif. Reponds « go N » a un radar pour en lancer un.</i>")
    for i, g in enumerate(go, 1):
        L.append("")
        L.append(_insight(g, i))
        detail = _detail_en_cours(g)          # detail Fait/En cours/Reste (uniquement en_cours/projet_bouge)
        if detail:
            L.append(detail)
    # Ligne dediee aux archives : un COMPTE, pas un detail (le detail reste lisible
    # dans go_suivi.json — rien n'est supprime, c'est juste sorti du bruit quotidien).
    if archives:
        L.append("")
        L.append(f"🗄 <i>{len(archives)} go archivé(s) (&gt;21j sans preuve) — "
                 f"conservé(s) dans go_suivi.json, rien n'est supprimé.</i>")
    L.append("")
    L.append("<i>Confirme quand tu veux : « fait N », « paye N &lt;montant&gt; », « skip N ».</i>")
    return "\n".join(L)


# ------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------

def _print_html_ascii(html: str) -> None:
    """Imprime en console une version ASCII debarrassee des balises (debug/local)."""
    txt = re.sub(r"</?[^>]+>", "", html)
    print(_safe(txt))


def main() -> int:
    args = sys.argv[1:]
    if "--llm" in args:
        i = args.index("--llm")
        cle = args[i + 1] if i + 1 < len(args) else ""
        r = inferer_llm(cle, force=("--force" in args))
        print(_safe(json.dumps(r, ensure_ascii=False)))
        return 0
    if "--radar" in args:
        _print_html_ascii(formater_section_radar() or "(aucun go en cours)")
        return 0
    if "--statut" in args:
        _print_html_ascii(formater_statut_complet())
        return 0
    # defaut / --refresh : regenere + resume console
    snap = rafraichir()
    print(f"go suivis : {len(snap['go'])}")
    for g in snap["go"]:
        print(f"  [{g['statut']:<17}] {_safe(g['projet']):<20} "
              f"commits={g.get('commits_depuis_go',0)}  {_safe(g['move_title'])[:44]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
