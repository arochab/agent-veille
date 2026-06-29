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
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VEILLE_ROOT = HERE.parent
DATA = VEILLE_ROOT / "data"
ATELIER_SNAP = DATA / "atelier.json"
VU = DATA / "vu.json"                 # memoire des URLs deja vues
OUT = DATA / "signaux_frais.json"     # sortie : seulement le neuf

# yt-dlp vit dans le venv agent-reach ; on le rend trouvable
VENV_BIN = Path(os.path.expanduser("~/.agent-reach-venv/Scripts"))


def safe(s: str) -> str:
    return str(s).encode("ascii", "replace").decode("ascii")


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def run(cmd: list[str], timeout: int = 60) -> tuple[bool, str]:
    """Lance une commande, renvoie (ok, stdout). Jamais d'exception qui plante tout."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                            encoding="utf-8", errors="replace")
        return (r.returncode == 0, r.stdout or "")
    except Exception as e:
        return (False, f"__ERR__ {e}")


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
    """Map projet -> requetes, base sur le snapshot atelier (donc auto a jour)."""
    out = {}
    for p in atelier.get("projets", []):
        nom = p["nom"]
        if nom in REQUETES_PAR_PROJET:
            out[nom] = REQUETES_PAR_PROJET[nom]
    return out


def collecte_github(req: str, limit: int = 6) -> list[dict]:
    ok, txt = run(["gh", "search", "repos", req, "--limit", str(limit),
                   "--sort", "updated", "--json", "fullName,description,url,updatedAt,stargazersCount"])
    if not ok:
        return []
    data = load_json_str(txt)
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
    return out


def load_json_str(txt: str):
    try:
        return json.loads(txt)
    except Exception:
        return None


def collecte_youtube(req: str, n: int = 3) -> list[dict]:
    ytdlp = VENV_BIN / "yt-dlp.exe"
    if not ytdlp.exists():
        return []
    ok, txt = run([str(ytdlp), "--flat-playlist", "--playlist-end", str(n),
                   "--print", "%(title)s\t%(webpage_url)s\t%(upload_date)s",
                   f"ytsearch{n}:{req}"], timeout=90)
    if not ok:
        return []
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
    return out


def main() -> int:
    atelier = load_json(ATELIER_SNAP, {})
    if not atelier:
        print("ERREUR: lance d'abord scan_atelier.py (data/atelier.json manquant).")
        return 1

    vu = set(load_json(VU, []))           # URLs deja vues
    requetes = derive_requetes(atelier)

    canaux_ok = {"github": False, "youtube": False}
    bruts: list[dict] = []

    for projet, reqs in requetes.items():
        for req in reqs:
            gh = collecte_github(req)
            if gh:
                canaux_ok["github"] = True
            yt = collecte_youtube(req)
            if yt:
                canaux_ok["youtube"] = True
            for item in gh + yt:
                item["projet"] = projet
                item["requete"] = req
                bruts.append(item)

    # Dedup + ne garder que le NEUF (URL jamais vue)
    frais = []
    vus_urls = set()
    for it in bruts:
        u = it["url"]
        if not u or u in vu or u in vus_urls:
            continue
        vus_urls.add(u)
        frais.append(it)

    # Met a jour la memoire des URLs vues (cumulatif)
    nouveau_vu = sorted(vu | {it["url"] for it in bruts if it["url"]})

    snap = {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "canaux_vivants": [c for c, v in canaux_ok.items() if v],
        "canaux_muets": [c for c, v in canaux_ok.items() if not v],
        "nb_bruts": len(bruts),
        "nb_frais": len(frais),
        "signaux_frais": frais,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    VU.write_text(json.dumps(nouveau_vu, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OK - canaux vivants: {snap['canaux_vivants'] or 'AUCUN'} | muets: {snap['canaux_muets'] or '-'}")
    print(f"     {len(bruts)} signaux bruts -> {len(frais)} NEUFS (le reste deja vu)")
    for it in frais[:12]:
        print(f"  [{it['canal']:<7}] {safe(it['titre'])[:55]:<55} <- {it['projet']}")
    if not frais:
        print("  (rien de neuf aujourd'hui -> brief silencieux, c'est voulu)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
