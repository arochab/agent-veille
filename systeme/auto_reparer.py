#!/usr/bin/env python3
"""
auto_reparer.py — Garde-fou de DERNIER RECOURS pour que la prod ne bloque JAMAIS.

Si un radar est recale par le jury pour des raisons MECANIQUES (title/pourquoi/do_now/
insight trop longs), ce module les raccourcit INTELLIGEMMENT (coupe a une frontiere de
phrase, jamais au milieu d'un mot) jusqu'a ce que le jury dise GO. Deterministe, sans LLM.

Il ne repare QUE la longueur (le cas le plus frequent). Le jargon / phrases creuses /
do_now vide / insight ABSENT sur le move star sont des defauts de FOND que seul le LLM
peut corriger -> dans ce cas on renvoie False (le .bat n'envoie pas + alerte). On ne
maquille jamais un vrai probleme (anti-hallucination : on n'invente pas un insight).

Usage : python systeme/auto_reparer.py data/radar.json
  Reecrit le fichier si reparable, exit 0 si le radar passe le jury apres reparation,
  1 s'il reste un defaut de fond non reparable mecaniquement.

Stdlib pure, robuste Windows.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jury_clarte as jc

# Limites du jury (importees pour rester synchronisees).
TITLE_MAX = jc.TITLE_MAX
POURQUOI_MAX = jc.POURQUOI_MAX
DO_NOW_MAX = jc.DO_NOW_MAX
INSIGHT_MAX = jc.INSIGHT_MAX


def raccourcir(texte: str, maxlen: int) -> str:
    """Coupe a la derniere frontiere de phrase/clause qui tient sous maxlen, sans
    couper un mot. Garde au moins la moitie du texte. Deterministe."""
    if not isinstance(texte, str) or len(texte) <= maxlen:
        return texte
    bout = texte[:maxlen]
    for sep, fin in ((". ", "."), (" : ", "."), (", ", "."), (" — ", "."), (" ", "")):
        i = bout.rfind(sep)
        if i > maxlen * 0.5:
            return bout[:i].rstrip(" ,—:") + fin
    # dernier recours : dernier mot entier
    return bout.rsplit(" ", 1)[0].rstrip(" ,—:") + "."


def reparer_longueurs(radar: dict) -> dict:
    """Raccourcit les champs trop longs de chaque move. Ne touche a rien d'autre."""
    for m in radar.get("moves", []) or []:
        if not isinstance(m, dict):
            continue
        if isinstance(m.get("title"), str):
            m["title"] = raccourcir(m["title"], TITLE_MAX)
        if isinstance(m.get("pourquoi_maintenant"), str):
            m["pourquoi_maintenant"] = raccourcir(m["pourquoi_maintenant"], POURQUOI_MAX)
        if isinstance(m.get("do_now"), str):
            m["do_now"] = raccourcir(m["do_now"], DO_NOW_MAX)
        if isinstance(m.get("insight"), str):
            m["insight"] = raccourcir(m["insight"], INSIGHT_MAX)
    return radar


def reparer(radar: dict) -> tuple[dict, bool]:
    """Repare les longueurs puis re-juge. Retourne (radar, go).
    go=True si le jury passe apres reparation ; False s'il reste un defaut de FOND
    (jargon, phrase creuse, do_now vide) qu'on ne maquille pas."""
    radar = reparer_longueurs(radar)
    verdict = jc.juger_radar(radar)
    return radar, verdict["go"]


def main() -> int:
    chemin = sys.argv[1] if len(sys.argv) > 1 else "data/radar.json"
    p = Path(chemin)
    if not p.exists():
        print(f"Fichier introuvable: {p}")
        return 2
    try:
        radar = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print("JSON illisible:", e)
        return 2

    avant = jc.juger_radar(radar)
    if avant["go"]:
        print("Radar deja GO - rien a reparer.")
        return 0

    radar, go = reparer(radar)
    if go:
        p.write_text(json.dumps(radar, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Radar REPARE (longueurs raccourcies proprement) -> jury GO.")
        return 0

    # Il reste un defaut de FOND : on ne maquille pas, on signale.
    v = jc.juger_radar(radar)
    print("NO-GO persistant apres reparation mecanique (defaut de FOND) :")
    for pb in v["problemes"]:
        if pb["bloquant"] and "trop long" not in pb["regle"]:
            ex = (pb["extrait"] or "").encode("ascii", "replace").decode("ascii")
            print(f"  [{pb['move']}] {pb['regle']}  ->  {ex}")
    print("  -> ces defauts demandent une reecriture par le LLM, pas un raccourci.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
