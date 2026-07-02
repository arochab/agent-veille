#!/usr/bin/env python3
"""
auto_sources.py — COUCHE 1 de l'auto-amelioration : les SOURCES & REQUETES.

PROBLEME RESOLU
  Les requetes de collecte (REQUETES_PAR_PROJET dans collecte_signaux.py) sont
  figees a la main. Le monde bouge : un subreddit devient chaud, une lib trans-projet
  emerge, une requete ne rapporte plus rien. Cette couche fait que le systeme
  AMELIORE TOUT SEUL la liste des requetes qu'il interroge, en regardant ce que les
  signaux deja collectes ont REELLEMENT rapporte (le score). Elle promeut ce qui
  marche, met au banc ce qui ne rapporte plus, et essaie quelques candidates.

GARDE-FOU CARDINAL — "JAMAIS PIRE QUE LA BASE FIGEE"
  Le SOCLE (les requetes de base_figee) est IMMORTEL : il n'est jamais retrograde ni
  banci, quoi qu'il arrive. Si la memoire est absente / corrompue / vide, ou si la
  moindre invariante est cassee, on RETOMBE sur base_figee. Cette couche ne peut donc
  JAMAIS degrader la collecte ; au pire elle est neutre.

CONTRAT
  - Stdlib uniquement (json, re, shutil, pathlib). Robuste Windows : aucune exception
    ne remonte au pipeline ; console ASCII ; fichiers UTF-8.
  - `observer` ne fait AUCUNE collecte reseau. Il lit `frais` (deja collecte + score)
    et la memoire, et n'a qu'un seul effet de bord : ecrire data/sources_memoire.json
    APRES validation des invariants (sinon il n'ecrit rien et garde l'ancien).
  - DETERMINISTE : meme (frais, memoire) -> meme memoire sortante. Pas d'horloge,
    pas de random. Tris explicites partout.

ETATS D'UNE REQUETE (champ "etat")
  socle  : requete de base_figee. Immortelle. Toujours interrogee.
  active : candidate qui a fait ses preuves (rendement EWMA >= SEUIL_VIE). Interrogee.
  essai  : candidate jeune (en periode d'essai). Interrogee.
  banc   : requete sortie du roulement (rendement trop bas). PAS interrogee. Gardee
           en memoire pour ne pas la re-decouvrir / re-essayer en boucle.

RENDEMENT (EWMA)
  A chaque run, pour chaque (projet, requete) on agrege les signaux frais :
    rendement_instant = score_median * (1 + part_signaux_score>=60)
  puis on lisse en EWMA : ewma = ALPHA*instant + (1-ALPHA)*ewma_precedent.
  -> une requete qui rapporte regulierement du score monte ; une qui se tarit redescend.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

# --- Emplacement de la memoire (data/sources_memoire.json). Patchable par les tests. ---
HERE = Path(__file__).resolve().parent
VEILLE_ROOT = HERE.parent
DATA = VEILLE_ROOT / "data"
MEM = DATA / "sources_memoire.json"     # tests : monkeypatch auto_sources.MEM vers un tmp

# --- Constantes de design (toutes en clair, auditables) ---
ALPHA = 0.3            # poids de l'observation du jour dans l'EWMA
SEUIL_VIE = 12.0       # rendement EWMA >= -> une candidate en essai peut devenir active
SEUIL_MORT = 8.0       # rendement EWMA < -> une active confirmee tombe au banc (hysteresis)
N_ACTIVES = 6          # plafond de requetes ACTIVE (hors socle) par projet
ESSAI_RUNS = 4         # nb de runs en essai avant de trancher promotion/banc
RUNS_MIN_ACTIF = 5     # une active n'est jugee "morte" qu'apres ce nb de runs (stabilite)
QUOTA_CAND = 2         # nb max de NOUVELLES candidates introduites par run

SEUIL_HAUT_SCORE = 60  # un signal est "haut score" a partir d'ici (sert part_haut_score)

ETATS_VALIDES = {"socle", "active", "essai", "banc"}
ETATS_INTERROGES = ("socle", "active", "essai")   # ordre stable pour la sortie

# Mini liste noire de jargon : une requete candidate qui en contient un mot est rejetee
# (on ne veut pas auto-generer des requetes creuses facon "leverage your moat").
JARGON_NOIR = {
    "leverage", "wedge", "moat", "synergy", "disrupt", "disruptive", "paradigm",
    "unlocks", "game-changer", "gamechanger", "north-star", "go-to-market",
    "positioning", "ecosystem", "holistic", "scalable", "next-gen", "cutting-edge",
}

# Mots vides ignores quand on fabrique des bi-grammes a partir des titres.
STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "at", "by",
    "with", "is", "are", "be", "this", "that", "your", "you", "it", "as", "from",
    "how", "i", "we", "my", "our", "new", "show", "hn", "vs", "via",
}


# =========================================================================
# Helpers purs
# =========================================================================
def _safe(s) -> str:
    """Repli ASCII pour la console Windows. Jamais d'exception."""
    try:
        return str(s).encode("ascii", "replace").decode("ascii")
    except Exception:
        return ""


def _charger_memoire():
    """Lit MEM. Renvoie un dict {projet: {requete: fiche}} OU None si absente/corrompue.
    None signale clairement 'pas de memoire exploitable' -> l'appelant fallback."""
    try:
        p = Path(MEM)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    projets = data.get("projets")
    if not isinstance(projets, dict):
        return None
    return data


def _fiche(etat: str, origine: str) -> dict:
    """Cree une fiche-requete neuve avec des compteurs a zero."""
    return {"etat": etat, "origine": origine, "ewma": 0.0, "runs": 0}


def _bootstrap(base_figee: dict) -> dict:
    """Construit une memoire neuve a partir de base_figee : chaque requete de base
    devient une fiche etat='socle', origine='socle'. (Le bug du squelette etait ici :
    `qs` mal scope ; on itere proprement projet par projet, requete par requete.)"""
    projets = {}
    for projet, requetes in (base_figee or {}).items():
        fiches = {}
        for q in (requetes or []):
            q = (q or "").strip()
            if not q:
                continue
            fiches[q] = _fiche("socle", "socle")
        projets[str(projet)] = fiches
    return {"projets": projets}


def _format_valide(q: str) -> bool:
    """Une requete candidate est-elle d'un format propre ?
    2..60 chars, non vide, pas d'URL, pas de retour ligne, au moins une lettre."""
    if not isinstance(q, str):
        return False
    q = q.strip()
    if not (2 <= len(q) <= 60):
        return False
    if "\n" in q or "\r" in q or "\t" in q:
        return False
    if "http://" in q or "https://" in q or "www." in q:
        return False
    if not re.search(r"[a-zA-Z]", q):
        return False
    return True


def jury_ok(q: str) -> bool:
    """Mini-jury de clarte pour une requete candidate (re-implementation simple de la
    logique de jury_clarte : on rejette le jargon brut et les formats sales).
    True = la requete est admissible. Jamais d'exception."""
    try:
        if not _format_valide(q):
            return False
        mots = set(re.findall(r"[a-z0-9][a-z0-9\-]*", q.lower()))
        if mots & JARGON_NOIR:
            return False
        return True
    except Exception:
        return False


def _median(valeurs) -> float:
    """Mediane d'une liste de nombres. Liste vide -> 0.0. Pur, deterministe."""
    xs = sorted(float(v) for v in valeurs)
    n = len(xs)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2.0


def _ngrammes_titre(titre: str):
    """Bi-grammes 'mot1 mot2' d'un titre, mots>=3 chars, hors stopwords. Deterministe."""
    mots = [m for m in re.findall(r"[a-z0-9]+", (titre or "").lower())
            if len(m) >= 3 and m not in STOPWORDS]
    return [f"{mots[i]} {mots[i + 1]}" for i in range(len(mots) - 1)]


# =========================================================================
# requetes_effectives — ce que la collecte doit interroger AUJOURD'HUI
# =========================================================================
def requetes_effectives(atelier: dict, base_figee: dict) -> dict:
    """Renvoie {projet: [requetes a interroger]} pour les projets de l'atelier.

    FALLBACK DUR : tout est sous try/except. Si la memoire est absente / corrompue /
    vide pour un projet, on retombe sur base_figee pour ce projet. La couche ne peut
    JAMAIS faire pire que base_figee : c'est le garde-fou cardinal.
    """
    try:
        base = base_figee or {}
        # Quels projets nous interessent : ceux de l'atelier qui ont une base figee.
        try:
            noms_atelier = [p.get("nom") for p in (atelier or {}).get("projets", [])
                            if isinstance(p, dict) and p.get("nom")]
        except Exception:
            noms_atelier = []
        # On vise l'intersection (comme derive_requetes), sinon a defaut toute la base.
        cibles = [n for n in noms_atelier if n in base] or list(base.keys())

        mem = _charger_memoire()
        projets_mem = (mem or {}).get("projets", {}) if isinstance(mem, dict) else {}

        out = {}
        for projet in cibles:
            base_proj = [q for q in (base.get(projet) or []) if (q or "").strip()]
            fiches = projets_mem.get(projet) if isinstance(projets_mem, dict) else None

            if not isinstance(fiches, dict) or not fiches:
                # Pas de memoire exploitable pour ce projet -> base figee pure.
                out[projet] = list(base_proj)
                continue

            # Memoire presente : on prend les requetes en etat interroge (socle/active/essai).
            requetes = []
            for q, f in fiches.items():
                if not isinstance(f, dict):
                    continue
                if f.get("etat") in ETATS_INTERROGES and (q or "").strip():
                    requetes.append(q)

            # Garde-fou : le socle de base_figee DOIT toujours etre present, meme si la
            # memoire l'a perdu pour une raison quelconque. On le re-injecte.
            for q in base_proj:
                if q not in requetes:
                    requetes.append(q)

            # Tri deterministe : socle d'abord (dans l'ordre de base_figee), puis le reste trie.
            socle_set = set(base_proj)
            reste = sorted(q for q in requetes if q not in socle_set)
            out[projet] = list(base_proj) + reste

            if not out[projet]:               # securite : jamais une liste vide
                out[projet] = list(base_proj)
        return out
    except Exception:
        # Filet ultime : on rend strictement base_figee.
        try:
            return {k: list(v or []) for k, v in (base_figee or {}).items()}
        except Exception:
            return {}


# =========================================================================
# observer — apprend des signaux frais et met a jour la memoire (validee)
# =========================================================================
def _agreger_par_requete(frais):
    """(projet, requete) -> {scores:[...], titres:[...], resumes:[...]}.
    Lecture pure de `frais` (signaux deja scores). Jamais d'exception."""
    agg = {}
    for it in (frais or []):
        if not isinstance(it, dict):
            continue
        projet = it.get("projet")
        requete = it.get("requete")
        if not projet or not requete:
            continue
        try:
            score = int(it.get("score", 0) or 0)
        except Exception:
            score = 0
        cle = (str(projet), str(requete))
        d = agg.setdefault(cle, {"scores": [], "titres": [], "resumes": []})
        d["scores"].append(score)
        d["titres"].append(str(it.get("titre", "") or ""))
        d["resumes"].append(str(it.get("resume", "") or ""))
    return agg


def _rendement_instant(scores) -> float:
    """score_median * (1 + part de signaux a score>=SEUIL_HAUT_SCORE). 0 si aucun signal."""
    if not scores:
        return 0.0
    med = _median(scores)
    hauts = sum(1 for s in scores if s >= SEUIL_HAUT_SCORE)
    part_haut = hauts / len(scores)
    return med * (1.0 + part_haut)


def _decouvrir_candidates(frais, mem):
    """Propose des requetes candidates a partir des signaux frais. Deterministe.
    Sources :
      (a) subreddits chauds  : resume reddit 'r/xxx - N upvotes' avec score>=60.
      (b) libs trans-projet  : titre github 'owner/repo' apparaissant sur >=2 projets.
      (c) bi-grammes porteurs: bi-grammes des titres haut-score (score>=60).
    Renvoie une liste de (projet, requete) candidates, deja filtrees jury_ok+format,
    et qui ne sont PAS deja connues en memoire (quel que soit leur etat). Triee.
    """
    projets_mem = mem.get("projets", {})

    def deja_connue(projet, q):
        fiches = projets_mem.get(projet)
        return isinstance(fiches, dict) and q in fiches

    candidates = set()         # ensemble de (projet, requete) -> dedup naturel
    repo_par_projets = {}      # repo "owner/repo" -> set(projets) ou il apparait haut-score

    for it in (frais or []):
        if not isinstance(it, dict):
            continue
        projet = it.get("projet")
        if not projet:
            continue
        projet = str(projet)
        try:
            score = int(it.get("score", 0) or 0)
        except Exception:
            score = 0
        if score < SEUIL_HAUT_SCORE:
            continue
        canal = it.get("canal", "")
        titre = str(it.get("titre", "") or "")
        resume = str(it.get("resume", "") or "")

        # (a) subreddit chaud -> requete "r/xxx"
        if canal == "reddit":
            m = re.search(r"\br/([A-Za-z0-9_]{2,30})\b", resume)
            if m:
                cand = f"r/{m.group(1)}"
                if jury_ok(cand) and not deja_connue(projet, cand):
                    candidates.add((projet, cand))

        # (b) lib trans-projet -> on accumule, decision apres la boucle
        if canal == "github":
            m = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$", titre.strip())
            if m:
                repo = f"{m.group(1)}/{m.group(2)}"
                repo_par_projets.setdefault(repo, set()).add(projet)

        # (c) bi-grammes porteurs des titres haut-score
        for bg in _ngrammes_titre(titre):
            # un bi-gramme est candidat sur SON projet
            if jury_ok(bg) and not deja_connue(projet, bg):
                candidates.add((projet, bg))

    # (b) suite : un repo vu haut-score sur >=2 projets devient candidate sur chacun.
    for repo, projets in repo_par_projets.items():
        if len(projets) >= 2 and jury_ok(repo):
            for projet in projets:
                if not deja_connue(projet, repo):
                    candidates.add((projet, repo))

    # Tri deterministe (projet puis requete) pour un choix reproductible sous quota.
    return sorted(candidates)


def _promotions(mem):
    """Applique l'hysteresis promotion/banc sur la memoire (in place). Deterministe.
    - essai : apres ESSAI_RUNS runs, devient 'active' si ewma>=SEUIL_VIE sinon 'banc'.
    - active : apres RUNS_MIN_ACTIF runs, tombe 'banc' si ewma<SEUIL_MORT.
    - SOCLE : jamais touche (immortel).
    - plafond N_ACTIVES par projet : si trop d'actives, les plus faibles repassent 'essai'
      (jamais banc directement par le plafond -> on leur laisse une chance).
    """
    for projet, fiches in mem.get("projets", {}).items():
        if not isinstance(fiches, dict):
            continue
        for q, f in fiches.items():
            if not isinstance(f, dict):
                continue
            etat = f.get("etat")
            if etat == "socle":
                continue          # IMMORTEL
            try:
                ewma = float(f.get("ewma", 0.0) or 0.0)
                runs = int(f.get("runs", 0) or 0)
            except Exception:
                ewma, runs = 0.0, 0

            if etat == "essai":
                if runs >= ESSAI_RUNS:
                    f["etat"] = "active" if ewma >= SEUIL_VIE else "banc"
            elif etat == "active":
                if runs >= RUNS_MIN_ACTIF and ewma < SEUIL_MORT:
                    f["etat"] = "banc"

        # Plafond N_ACTIVES : on garde les meilleures actives, le surplus repasse essai.
        actives = [(q, f) for q, f in fiches.items()
                   if isinstance(f, dict) and f.get("etat") == "active"]
        if len(actives) > N_ACTIVES:
            # Tri deterministe : ewma desc, puis requete asc (depart-egalite stable).
            actives.sort(key=lambda kv: (-float(kv[1].get("ewma", 0.0) or 0.0), kv[0]))
            for q, f in actives[N_ACTIVES:]:
                f["etat"] = "essai"
                # on ne remet pas runs a 0 : l'historique d'EWMA reste, c'est voulu.


def _valider(mem, base_figee) -> bool:
    """Verifie les invariants AVANT ecriture. Si un seul casse -> False (on n'ecrit pas).
    Invariants :
      - structure dict {projets:{projet:{requete:fiche}}} serialisable JSON ;
      - chaque etat dans ETATS_VALIDES ;
      - pas de requete vide ;
      - SOCLE INTACT : toute requete de base_figee est presente, etat='socle',
        origine='socle' (le socle n'a pas ete retrograde/supprime) ;
      - total actives (hors socle) <= N_ACTIVES par projet.
    """
    try:
        if not isinstance(mem, dict):
            return False
        projets = mem.get("projets")
        if not isinstance(projets, dict):
            return False

        # Serialisable JSON (sinon l'ecriture echouerait silencieusement plus tard).
        json.dumps(mem, ensure_ascii=False)

        for projet, fiches in projets.items():
            if not isinstance(fiches, dict):
                return False
            n_actives = 0
            for q, f in fiches.items():
                if not isinstance(q, str) or not q.strip():
                    return False          # requete vide
                if not isinstance(f, dict):
                    return False
                if f.get("etat") not in ETATS_VALIDES:
                    return False
                if f.get("etat") == "active":
                    n_actives += 1
            if n_actives > N_ACTIVES:
                return False

        # SOCLE INTACT : base_figee entierement presente et marquee socle.
        for projet, requetes in (base_figee or {}).items():
            fiches = projets.get(projet)
            if not isinstance(fiches, dict):
                return False
            for q in (requetes or []):
                q = (q or "").strip()
                if not q:
                    continue
                f = fiches.get(q)
                if not isinstance(f, dict):
                    return False
                if f.get("etat") != "socle" or f.get("origine") != "socle":
                    return False
        return True
    except Exception:
        return False


def _ecrire_memoire(mem) -> bool:
    """Ecrit MEM en UTF-8 avec backup .bak prealable (rollback possible). Atomique-ish :
    on ecrit dans un .tmp puis on remplace. Jamais d'exception remontante."""
    try:
        p = Path(MEM)
        p.parent.mkdir(parents=True, exist_ok=True)
        # backup de l'ancien etat si present
        if p.exists():
            try:
                shutil.copyfile(str(p), str(p) + ".bak")
            except Exception:
                pass
        tmp = Path(str(p) + ".tmp")
        tmp.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
        return True
    except Exception:
        return False


def observer(frais, base_figee, jury_ok=jury_ok) -> bool:
    """Met a jour la memoire des sources a partir des signaux frais du jour.

    AUCUNE collecte reseau : on lit juste `frais` (deja collecte + score). Pur sauf
    l'ecriture finale, qui n'a lieu QUE si _valider passe (sinon l'ancienne memoire
    reste intacte). DETERMINISTE.

    Retourne True si la memoire a ete ecrite, False sinon (validation KO ou ecriture KO).
    `jury_ok` est injectable (defaut : le jury_ok du module) pour testabilite.
    """
    try:
        # --- 0) GARDIEN : ne JAMAIS s'auto-modifier si le systeme n'est pas sain.
        # Organe vital altere ou HALT.flag present -> on ne touche a rien (faille reine).
        try:
            import immunite
            if not immunite.verifier()["ok"]:
                return False
        except Exception:
            pass  # immunite absente -> on n'empeche pas le fonctionnement de base

        # --- 1) charger ou bootstrap depuis base_figee ---
        mem = _charger_memoire()
        if mem is None or not mem.get("projets"):
            mem = _bootstrap(base_figee)
        else:
            # S'assurer que tout le socle de base_figee existe (auto-reparation douce).
            projets = mem.setdefault("projets", {})
            for projet, requetes in (base_figee or {}).items():
                fiches = projets.setdefault(str(projet), {})
                for q in (requetes or []):
                    q = (q or "").strip()
                    if not q:
                        continue
                    f = fiches.get(q)
                    if not isinstance(f, dict):
                        fiches[q] = _fiche("socle", "socle")
                    else:
                        # le socle reste socle, quoi qu'il arrive
                        f["etat"] = "socle"
                        f["origine"] = "socle"

        projets = mem.setdefault("projets", {})

        # --- 2) agreger + 3) EWMA et compteurs de runs ---
        agg = _agreger_par_requete(frais)

        for projet, fiches in projets.items():
            if not isinstance(fiches, dict):
                continue
            for q, f in fiches.items():
                if not isinstance(f, dict):
                    continue
                # une requete au banc n'est plus interrogee -> elle ne "tourne" pas,
                # on ne met a jour ni son ewma ni ses runs (elle dort).
                if f.get("etat") == "banc":
                    continue
                scores = agg.get((str(projet), str(q)), {}).get("scores", [])
                instant = _rendement_instant(scores)
                try:
                    ewma_prec = float(f.get("ewma", 0.0) or 0.0)
                    runs_prec = int(f.get("runs", 0) or 0)
                except Exception:
                    ewma_prec, runs_prec = 0.0, 0
                f["ewma"] = ALPHA * instant + (1.0 - ALPHA) * ewma_prec
                f["runs"] = runs_prec + 1

        # --- 4) decouverte de candidates (quota) ---
        candidates = _decouvrir_candidates(frais, mem)
        introduites = 0
        for projet, q in candidates:
            if introduites >= QUOTA_CAND:
                break
            if not jury_ok(q):
                continue
            fiches = projets.setdefault(projet, {})
            if q in fiches:                 # deja connue -> on ne re-cree pas
                continue
            # combien d'actives a ce projet ? si plafond atteint, l'essai reste un essai
            # (il ne pourra devenir active que si une place se libere). On l'ajoute quand meme.
            fiches[q] = _fiche("essai", "decouverte")
            introduites += 1

        # --- promotions / banc / plafond (apres MAJ des compteurs) ---
        _promotions(mem)

        # --- 5) VALIDATION avant ecriture ---
        if not _valider(mem, base_figee):
            return False

        # --- 6) backup + ecriture ---
        return _ecrire_memoire(mem)
    except Exception:
        # Aucune exception ne doit remonter au pipeline. On n'a rien ecrit.
        return False


# =========================================================================
# CLI / auto-demo minimal (ASCII). Ne touche PAS au vrai fichier sans data/.
# =========================================================================
def main() -> int:
    """Petit run de demonstration sur la base figee de collecte_signaux, lecture seule
    cote reseau. Affiche les requetes effectives. ASCII only."""
    try:
        from collecte_signaux import REQUETES_PAR_PROJET as BASE
    except Exception:
        BASE = {"demo": ["requete une", "requete deux"]}
    atelier = {"projets": [{"nom": k} for k in BASE]}
    eff = requetes_effectives(atelier, BASE)
    print("Requetes effectives (memoire %s):" % ("presente" if _charger_memoire() else "absente -> base figee"))
    for projet in sorted(eff):
        print("  [%s]" % _safe(projet))
        for q in eff[projet]:
            print("     - %s" % _safe(q))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
