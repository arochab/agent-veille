#!/usr/bin/env python3
"""
collecte_signaux.py — Va chercher les nouveautes du monde (GitHub + Web + YouTube)
sur des requetes derivees de l'atelier, et ne garde QUE ce qui est NEUF.

Pourquoi "que le neuf" : un brief quotidien qui repete les memes liens = on arrete
de le lire en 3 jours. On garde une memoire des URLs deja vues (data/vu.json) et on
ne ressort que les nouvelles. Si rien de neuf un jour -> brief vide -> silence.

Robuste Windows (console ASCII, encodage UTF-8 pour les fichiers).
Lecture seule cote atelier. N'ecrit QUE dans agent-earch-veille/data/.
Degrade proprement : un canal qui echoue est marque, pas invente.

DEUX GARDE-FOUS AJOUTES (tache #3) :
  (b) PANNE != JOUR CALME. Un canal qui RENVOIE une erreur (process KO, timeout,
      HTTP != 200) est un INCIDENT, distinct d'un canal qui repond mais sans neuf.
      -> champ "incidents" dans signaux_frais.json + "canaux_muets" reserve aux pannes.
  (c) SAS ANTI-BRULURE. On ne marque PLUS une URL "vue" au moment de la collecte.
      Les URLs du jour partent dans un SAS (data/vu_sas.json). Elles ne rejoignent
      vu.json qu'au PROCHAIN run reussi (donc apres avoir eu une chance de servir).
      Resultat : un crash entre collecte et livraison ne brule pas les signaux.

COLLECTE PARALLELE : chaque (canal, requete) part dans un ThreadPoolExecutor au
lieu d'attendre la requete precedente. Une source lente ne ralentit plus tout le
run du matin. Les resultats sont REASSEMBLES dans l'ordre de soumission (identique
a l'ancien ordre sequentiel projet -> requete -> canal), donc l'ordre d'arrivee
des threads ne fuit JAMAIS dans la sortie : memes entrees, meme signaux_frais.json.
Toutes les ecritures fichiers restent dans le thread principal, apres la collecte.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, CancelledError, wait as futures_wait
from datetime import datetime, timezone
from pathlib import Path

# Ecriture atomique (audit Fable, P1-4) : vu.json/vu_sas.json/signaux_frais.json
# sont la memoire de dedup ANTI-BRULURE -> un crash mid-write ne doit jamais la
# tronquer (sinon re-flood de vieux signaux au run suivant).
try:
    from atomic_io import write_json_atomic
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from atomic_io import write_json_atomic

# Scoring des signaux (valeur business x fraicheur x actionnabilite, anti-vanite).
# collecte_signaux.py est lance avec cwd=systeme/ par veille.py ; import direct OK.
try:
    from scoring import scorer_tous
except Exception:  # fallback si lance depuis un autre cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scoring import scorer_tous

# Couche 1 (auto-amelioration des sources). Si le module manque -> on continue
# exactement comme avant (dict fige). La couche ne peut JAMAIS degrader la collecte.
try:
    import auto_sources
except Exception:
    auto_sources = None

HERE = Path(__file__).resolve().parent
VEILLE_ROOT = HERE.parent
DATA = VEILLE_ROOT / "data"
ATELIER_SNAP = DATA / "atelier.json"
VU = DATA / "vu.json"                 # memoire des URLs deja vues (definitif)
VU_SAS = DATA / "vu_sas.json"         # SAS : URLs du dernier run, en attente de promotion
OUT = DATA / "signaux_frais.json"     # sortie : seulement le neuf

# yt-dlp vit dans le venv agent-reach ; on le rend trouvable
VENV_BIN = Path(os.path.expanduser("~/.agent-reach-venv/Scripts"))

# Canaux qu'on considere "censes etre vivants" : leur silence = PANNE, pas jour calme.
# (HN et GitHub sont des API publiques fiables ; YouTube depend d'un binaire local
#  optionnel, donc son absence n'est PAS traitee comme une panne dure.)
CANAUX_VITAUX_FIXES = {"github", "hackernews"}


def _canaux_vitaux() -> set:
    """CANAUX_VITAUX_FIXES + reddit SI rdt.exe est installe (audit Fable, P1-3).
    Reddit porte le panier ARGENT ([hiring]/will pay vivent a 95% la -> scoring.py).
    'Vital-si-configure' : si Adam n'a JAMAIS installe rdt, son absence est normale
    (pas une panne) ; s'il l'a installe et qu'il se tait (cookie expire), c'est une
    VRAIE panne qui doit alerter -> sinon le canal argent peut mourir des semaines
    sans que The Wire le dise (c'etait le trou avant ce fix)."""
    rdt = VENV_BIN / "rdt.exe"
    if rdt.exists():
        return CANAUX_VITAUX_FIXES | {"reddit"}
    return set(CANAUX_VITAUX_FIXES)


def safe(s: str) -> str:
    return str(s).encode("ascii", "replace").decode("ascii")


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def run(cmd: list[str], timeout: int = 60) -> tuple[bool, str]:
    """Lance une commande, renvoie (ok, stdout). Jamais d'exception qui plante tout.
    ok=False signale un VRAI echec (code != 0, timeout, exception) -> incident potentiel.
    On force PYTHONIOENCODING=utf-8 : certains CLI (rdt) ecrivent des emojis et
    plantent sur une console Windows cp1252 sinon (UnicodeEncodeError)."""
    try:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                            encoding="utf-8", errors="replace", env=env)
        if r.returncode != 0:
            return (False, f"__ERR__ exit={r.returncode} {(r.stderr or '').strip()[:200]}")
        return (True, r.stdout or "")
    except subprocess.TimeoutExpired:
        return (False, "__ERR__ timeout")
    except Exception as e:
        return (False, f"__ERR__ {e}")


def http_get(url: str, timeout: int = 20) -> tuple[bool, str]:
    """GET HTTP simple (stdlib). (ok, body). ok=False = incident reseau/HTTP."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "the-wire/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (True, r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return (False, f"__ERR__ HTTP {e.code}")
    except Exception as e:
        return (False, f"__ERR__ {e}")


def load_json_str(txt: str):
    try:
        return json.loads(txt)
    except Exception:
        return None


# ---- Requetes derivees de l'atelier ----
# Chaque projet -> quelques requetes ciblees. Future-proof : si un nouveau projet
# apparait avec un resume, on lui derive des requetes generiques par mots-cles.
REQUETES_PAR_PROJET = {
    "cuepoint": ["AI mixing assistant", "audio mix analyzer browser"],
    "mixhub": ["peer to peer gear rental trust", "DJ equipment rental marketplace"],
    "claude-eats-tokens": ["claude code usage tracker", "LLM token cost dashboard"],
    "serp-scraper": ["AI visibility GEO checker", "generative engine optimization tool"],
    "axis-command-os": ["AI agent orchestration intent router"],
    "prism": ["CSV analytics dashboard tool"],
    "stratum": ["figma MCP design automation"],
}


def derive_requetes(atelier: dict) -> dict:
    """Map projet -> requetes, base sur le snapshot atelier (donc auto a jour).
    data/projets.json en priorite (audit Fable, reco #4) ; REQUETES_PAR_PROJET
    reste le repli fige a l'identique si absent/corrompu ou si le projet n'y a
    pas encore de requetes definies (liste vide -> on garde l'ancien dict)."""
    out = {}
    for p in atelier.get("projets", []):
        nom = p["nom"]
        requetes = None
        try:
            from config_projets import requetes_de
            requetes = requetes_de(nom)
        except Exception:
            requetes = None
        if not requetes:  # None (fichier absent) OU [] (projet sans requetes) -> repli
            requetes = REQUETES_PAR_PROJET.get(nom)
        if requetes:
            out[nom] = requetes
    return out


# ---- Collecteurs : chacun renvoie (items, erreur_ou_None) ----
# erreur != None => INCIDENT sur ce canal pour cette requete.

def collecte_github(req: str, limit: int = 6) -> tuple[list[dict], str | None]:
    ok, txt = run(["gh", "search", "repos", req, "--limit", str(limit),
                   "--sort", "updated", "--json", "fullName,description,url,updatedAt,stargazersCount"])
    if not ok:
        return ([], txt)  # txt contient "__ERR__ ..."
    data = load_json_str(txt)
    if data is None:
        return ([], "__ERR__ json-illisible")
    out = []
    for r in data or []:
        out.append({
            "canal": "github",
            "titre": r.get("fullName", ""),
            "url": r.get("url", ""),
            "resume": (r.get("description") or "")[:200],
            "date": (r.get("updatedAt") or "")[:10],
            "etoiles": r.get("stargazersCount", 0),
        })
    return (out, None)


def collecte_hackernews(req: str, n: int = 6) -> tuple[list[dict], str | None]:
    """HN via l'API Algolia (gratuite, pas de cookie)."""
    import urllib.parse
    q = urllib.parse.quote(req)
    url = f"https://hn.algolia.com/api/v1/search?query={q}&tags=story&hitsPerPage={n}"
    ok, body = http_get(url)
    if not ok:
        return ([], body)
    data = load_json_str(body)
    if data is None:
        return ([], "__ERR__ json-illisible")
    out = []
    for h in (data.get("hits") or []):
        link = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID','')}"
        ts = h.get("created_at", "")
        out.append({
            "canal": "hackernews",
            "titre": h.get("title") or "",
            "url": link,
            "resume": (h.get("story_text") or "")[:200],
            "date": ts[:10],
            "etoiles": h.get("points", 0),
        })
    return (out, None)


def collecte_youtube(req: str, n: int = 3) -> tuple[list[dict], str | None]:
    ytdlp = VENV_BIN / "yt-dlp.exe"
    if not ytdlp.exists():
        # Binaire absent : ce n'est PAS une panne du canal, juste indisponible.
        return ([], None)
    ok, txt = run([str(ytdlp), "--flat-playlist", "--playlist-end", str(n),
                   "--print", "%(title)s\t%(webpage_url)s\t%(upload_date)s",
                   f"ytsearch{n}:{req}"], timeout=90)
    if not ok:
        return ([], txt)
    out = []
    for line in txt.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].startswith("http"):
            d = parts[2] if len(parts) > 2 and len(parts[2]) == 8 else ""
            out.append({
                "canal": "youtube",
                "titre": parts[0],
                "url": parts[1],
                "resume": "",
                "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if d else "",
            })
    return (out, None)


def collecte_reddit(req: str, n: int = 4) -> tuple[list[dict], str | None]:
    """Canal DEMANDE : Reddit via rdt-cli (compte jetable, cookie local).
    Capte les vraies discussions/besoins (qui cherche, qui se plaint = acheteur).
    Si rdt absent ou non connecte, ce n'est PAS une panne dure -> ([], None)."""
    rdt = VENV_BIN / "rdt.exe"
    if not rdt.exists():
        return ([], None)
    # Sortie JSON pour parsing fiable ; rdt rend du YAML par defaut, --json sinon.
    ok, txt = run([str(rdt), "search", req, "--limit", str(n), "--json"], timeout=40)
    if not ok:
        # rdt.exe existe mais echoue = tres probablement le cookie jetable qui a expire.
        # Reddit est VITAL des lors que rdt.exe est installe (_canaux_vitaux) -> ceci
        # remonte en incident publie, message actionnable pour Adam.
        return ([], f"rdt-cli KO (cookie Reddit probablement expire) :: {txt}")
    data = load_json_str(txt)
    if data is None:
        return ([], "__ERR__ json-illisible")
    out = []
    try:
        children = data.get("data", {}).get("data", {}).get("children", []) or []
    except Exception:
        children = []
    for c in children:
        d = (c or {}).get("data", {})
        title = d.get("title") or ""
        perma = d.get("permalink") or ""
        url = f"https://www.reddit.com{perma}" if perma else (d.get("url") or "")
        if not title or not url:
            continue
        sub = d.get("subreddit", "")
        ups = d.get("ups", 0)
        ts = d.get("created_utc", 0)
        date = ""
        try:
            if ts:
                date = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            date = ""
        out.append({
            "canal": "reddit",
            "titre": title[:200],
            "url": url,
            "resume": f"r/{sub} - {ups} upvotes",
            "date": date,
        })
    return (out, None)


COLLECTEURS = {
    "github": collecte_github,
    "hackernews": collecte_hackernews,
    "reddit": collecte_reddit,
    "youtube": collecte_youtube,
}

# ---- Parallelisation de la collecte ----
# 8 workers : assez pour absorber ~40-50 taches (canal x requete) sans marteler
# les API ; chaque tache garde son timeout reseau individuel (run()/http_get()).
MAX_WORKERS = 8
# Filet global : si le pool depasse ce budget (sources qui rament toutes en meme
# temps), on n'attend plus — les taches non terminees deviennent des incidents.
# Les taches deja lancees restent bornees par leur timeout individuel (<= 90s).
TIMEOUT_GLOBAL_POOL = 300  # secondes

# Marqueur d'erreur pour une tache sacrifiee par le timeout global du pool.
ERR_TIMEOUT_POOL = "__ERR__ timeout global du pool de collecte"


def _tache_collecte(fn, req: str) -> tuple[list[dict], str | None]:
    """Enveloppe d'une tache de collecte executee dans un thread du pool.
    Pourquoi : les collecteurs sont concus pour ne jamais lever, mais si un bug
    imprevu leve quand meme, on le convertit en erreur de canal (incident visible)
    au lieu de laisser une exception orpheline dans un thread. Fonction PURE :
    aucune ecriture fichier ni etat partage ici (thread-safety par construction)."""
    try:
        return fn(req)
    except Exception as e:
        return ([], f"__ERR__ exception collecteur: {e}")


def collecter_en_parallele(taches: list[tuple]) -> list[tuple[list[dict], str | None]]:
    """Execute toutes les taches (projet, requete, canal, fn) en parallele et
    renvoie les resultats DANS L'ORDRE DE SOUMISSION — jamais l'ordre d'arrivee
    des threads. C'est ce qui garantit le determinisme : la liste renvoyee est
    alignee index a index sur `taches`, donc bruts/dedup/tri par score voient
    exactement le meme ordre que l'ancienne boucle sequentielle (scorer_tous est
    un tri stable : a scores egaux, l'ordre d'origine — deterministe — est garde).
    Timeout global : les taches pas finies a temps sont annulees (jamais demarrees)
    ou abandonnees (bornees par leur timeout individuel) et rendent une erreur."""
    resultats: list[tuple[list[dict], str | None]] = []
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        futures = [pool.submit(_tache_collecte, fn, req) for (_p, req, _c, fn) in taches]
        _, pas_finies = futures_wait(futures, timeout=TIMEOUT_GLOBAL_POOL)
        for f in pas_finies:
            f.cancel()  # n'annule que ce qui n'a pas encore demarre
        for f in futures:
            if f in pas_finies:
                # Ni le resultat ni l'attente : tache sacrifiee par le budget global.
                resultats.append(([], ERR_TIMEOUT_POOL))
                continue
            try:
                resultats.append(f.result())
            except CancelledError:
                resultats.append(([], ERR_TIMEOUT_POOL))
            except Exception as e:  # ceinture + bretelles (deja capte dans _tache_collecte)
                resultats.append(([], f"__ERR__ {e}"))
    finally:
        # wait=False : on ne bloque pas sur d'eventuelles retardataires (bornees
        # par leurs timeouts individuels) ; cancel_futures purge la file d'attente.
        pool.shutdown(wait=False, cancel_futures=True)
    return resultats


def main() -> int:
    atelier = load_json(ATELIER_SNAP, {})
    if not atelier:
        print("ERREUR: lance d'abord scan_atelier.py (data/atelier.json manquant).")
        return 1

    # --- SAS : on PROMEUT d'abord le sas precedent vers vu.json ---
    # Les URLs collectees au run N-1 ont eu leur chance de servir (analyse + Telegram).
    # On les grave maintenant comme "vues" pour de bon. C'est le coeur du garde-fou (c).
    vu = set(load_json(VU, []))
    sas_precedent = set(load_json(VU_SAS, []))
    if sas_precedent:
        vu |= sas_precedent
        write_json_atomic(VU, sorted(vu))

    # Requetes a interroger : couche 1 si dispo (apprend quelles requetes rapportent),
    # sinon le dict fige. Fallback dur garanti dans requetes_effectives.
    base_figee = derive_requetes(atelier)
    if auto_sources is not None:
        try:
            requetes = auto_sources.requetes_effectives(atelier, base_figee)
        except Exception:
            requetes = base_figee   # au pire, exactement comme avant
    else:
        requetes = base_figee

    # Plan de collecte : une tache par (canal, requete), dans l'ordre historique
    # projet -> requete -> canal. Cet ordre de soumission EST l'ordre de depouillement
    # (voir collecter_en_parallele), donc la sortie reste deterministe au bit pres.
    taches: list[tuple] = []
    for projet, reqs in requetes.items():
        for req in reqs:
            for canal, fn in COLLECTEURS.items():
                taches.append((projet, req, canal, fn))

    resultats = collecter_en_parallele(taches)

    # Statut par canal — depouille dans le THREAD PRINCIPAL, en ordre de soumission
    # (thread-safe par construction : aucun etat partage entre threads) :
    #   reponses[canal]   = au moins une requete a repondu sans erreur
    #   incidents_canal[c] = dernier message d'erreur rencontre sur ce canal
    reponses: dict[str, bool] = {}
    incidents_canal: dict[str, str] = {}
    bruts: list[dict] = []

    for (projet, req, canal, _fn), (items, err) in zip(taches, resultats):
        if err is not None:
            incidents_canal[canal] = err  # garde la derniere erreur vue
        else:
            reponses[canal] = True
        for item in items:
            item["projet"] = projet
            item["requete"] = req
            bruts.append(item)

    # --- Classement des canaux : vivant / muet-calme / EN PANNE ---
    # Un canal est EN PANNE s'il est vital (reddit inclus SI rdt.exe est installe -
    # voir _canaux_vitaux), n'a JAMAIS repondu, et a eu >=1 erreur.
    canaux_vivants = sorted(reponses.keys())
    canaux_en_panne = sorted(
        c for c in _canaux_vitaux()
        if not reponses.get(c, False) and c in incidents_canal
    )
    incidents = [
        {"canal": c, "erreur": incidents_canal[c]}
        for c in canaux_en_panne
    ]

    # Dedup + ne garder que le NEUF (URL jamais vue) — on compare au vu.json DEFINITIF
    frais = []
    vus_urls = set()
    for it in bruts:
        u = it["url"]
        if not u or u in vu or u in vus_urls:
            continue
        vus_urls.add(u)
        frais.append(it)

    # --- SCORING : on note + trie les frais pendant qu'ils portent encore
    # etoiles/canal/date (veille.py les perdra en compactant). Pur & deterministe :
    # on passe "aujourd'hui" explicitement (date du run), jamais via la fonction de score.
    aujourdhui = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        frais = scorer_tous(frais, aujourdhui)  # ajoute "score"+"raisons", trie desc
    except Exception as e:
        print(f"  (scoring indisponible: {safe(str(e))[:80]} -> ordre non trie)")

    # --- COUCHE 1 APPREND : observe ce que chaque requete a rapporte (cash-proxy),
    # promeut/bance, decouvre des candidates. Pur sauf l'ecriture validee. Jamais bloquant.
    if auto_sources is not None:
        try:
            maj = auto_sources.observer(frais, base_figee)
            if maj:
                print("  [auto] memoire des sources mise a jour (couche 1)")
        except Exception as e:
            print(f"  [auto] observer ignore (non bloquant): {safe(str(e))[:60]}")

    # --- SAS (c) : on N'AJOUTE PAS a vu.json maintenant. ---
    # On depose les URLs brutes du jour dans le sas. Elles seront promues au PROCHAIN
    # run reussi. Donc une URL fraiche reste "neuve" tant qu'elle n'a pas survecu a un
    # cycle complet. Un crash apres ce point ne brule rien.
    sas_aujourdhui = sorted({it["url"] for it in bruts if it["url"]})
    write_json_atomic(VU_SAS, sas_aujourdhui)

    snap = {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "canaux_vivants": canaux_vivants,
        "canaux_muets": canaux_en_panne,   # desormais = PANNES uniquement (pas "calme")
        "incidents": incidents,            # detail des pannes (canal + erreur)
        "panne": bool(incidents),          # drapeau simple pour le .bat / Telegram
        "nb_bruts": len(bruts),
        "nb_frais": len(frais),
        "signaux_frais": frais,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    write_json_atomic(OUT, snap)

    etat = "PANNE" if incidents else "OK"
    print(f"{etat} - canaux vivants: {canaux_vivants or 'AUCUN'} | en panne: {canaux_en_panne or '-'}")
    if incidents:
        for inc in incidents:
            print(f"  !! INCIDENT canal '{inc['canal']}': {safe(inc['erreur'])[:80]}")
    print(f"     {len(bruts)} signaux bruts -> {len(frais)} NEUFS (le reste deja vu), tries par score")
    for it in frais[:12]:
        sc = it.get("score", 0)
        print(f"  [{sc:>3}] [{it['canal']:<10}] {safe(it['titre'])[:45]:<45} <- {it['projet']}")
    if not frais and not incidents:
        print("  (rien de neuf aujourd'hui -> brief silencieux, c'est voulu)")
    # Code retour : 0 si tout va bien OU jour calme ; 2 si PANNE (le .bat le repere).
    return 2 if incidents else 0


if __name__ == "__main__":
    sys.exit(main())
