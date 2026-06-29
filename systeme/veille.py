#!/usr/bin/env python3
"""
veille.py — Chef d'orchestre du pipeline de veille.

Une seule commande lance toute la chaine de COLLECTE :
  1. scan_atelier.py     -> data/atelier.json     (tous les projets, a jour)
  2. collecte_signaux.py -> data/signaux_frais.json (seulement le NEUF)
  3. prepare le dossier d'entree pour l'analyse (data/_pour_analyse.json)

L'etape d'ANALYSE (produire le radar dans le format valide) est faite par un
Claude qui lit data/_pour_analyse.json + systeme/PROMPT_RADAR.md. C'est la seule
etape qui demande un Claude (un cron ne peut pas le declencher) -> voir l'option
"routine cloud" pour l'automatiser, ou lancer la commande du matin.

Lecture seule cote atelier. N'ecrit QUE dans data/. Robuste Windows.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VEILLE_ROOT = HERE.parent
DATA = VEILLE_ROOT / "data"
PY = sys.executable


def step(label: str, script: str) -> bool:
    print(f"\n>>> {label}")
    r = subprocess.run([PY, str(HERE / script)], cwd=str(VEILLE_ROOT))
    return r.returncode == 0


def prepare_analyse() -> int:
    """Compacte signaux_frais.json en _pour_analyse.json (titre/url/canal/projet/date)."""
    src = DATA / "signaux_frais.json"
    if not src.exists():
        print("  (pas de signaux_frais.json — rien a preparer)")
        return 0
    d = json.loads(src.read_text(encoding="utf-8"))
    items = [{"t": s["titre"], "u": s["url"], "c": s["canal"], "p": s["projet"], "d": s.get("date", "")}
             for s in d.get("signaux_frais", [])]
    (DATA / "_pour_analyse.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return len(items)


def main() -> int:
    print("=== VEILLE — pipeline de collecte ===")
    if not step("1/3 Scan de l'atelier", "scan_atelier.py"):
        print("ECHEC au scan de l'atelier. Stop.")
        return 1
    if not step("2/3 Collecte des signaux frais", "collecte_signaux.py"):
        print("ECHEC a la collecte. Stop.")
        return 1
    print("\n>>> 3/3 Preparation pour l'analyse")
    n = prepare_analyse()
    print(f"  {n} signaux frais prets pour l'analyse -> data/_pour_analyse.json")

    print("\n=== COLLECTE TERMINEE ===")
    if n == 0:
        print("Rien de neuf aujourd'hui -> brief silencieux (c'est voulu).")
    else:
        print(f"{n} signaux neufs. Etape suivante (analyse -> radar) :")
        print("  un Claude lit data/_pour_analyse.json + systeme/PROMPT_RADAR.md")
        print("  et ecrit briefs/AAAA-MM-JJ_radar.md au format valide.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
