#!/usr/bin/env python3
"""
jury_clarte.py — JURY GO/NO-GO de CLARTE (garde-fou final, par regles, sans LLM).

Bloque un radar AVANT envoi Telegram s'il n'est pas limpide. Criteres d'Adam :
  1. Chaque move dit clairement QUOI FAIRE (do_now non vide et concret).
  2. Compris en 3 secondes (title court, present).
  3. Zero phrase creuse (liste noire) et zero jargon brut non traduit.

Usage : python systeme/jury_clarte.py [data/radar.json]
  Exit 0 = GO (clair).  Exit 1 = NO-GO (un probleme bloquant) -> le .bat n'envoie pas.

Stdlib pure, deterministe, robuste Windows (console ASCII). Reglages en haut de fichier.
"""
from __future__ import annotations
import json
import sys
import unicodedata
from pathlib import Path

TITLE_MAX = 95       # caracteres : au-dela, plus scannable en 3 sec
POURQUOI_MAX = 200
DO_NOW_MAX = 240
INSIGHT_MAX = 160    # SPEC-INSIGHT-2B : la lecture strategique du move, meme discipline que title

# Phrases creuses : presentes n'importe ou dans le move -> bloquant.
PHRASES_CREUSES = [
    "le creneau est ouvert", "creneau est ouvert", "c'est ton angle", "ton angle",
    "ton edge", "ton asymetrie", "une longueur d'avance", "longueur d'avance",
    "game changer", "game-changer", "change la donne", "disruptif", "incontournable",
    "la demande croit", "l'ia explose", "saisis l'opportunite", "c'est le moment",
    "ne rate pas", "a ne pas manquer", "revolutionnaire",
]
# Jargon anglais brut non traduit : present tel quel -> bloquant.
JARGON_BRUT = [
    "unlocks", "rivals miss", "wedge", "positioning", "leverage", "moat",
    "take rate", "churn", "mrr", "arr", "funnel", "north star", "go-to-market",
    "product-market fit", "cac", "ltv",
]
# Verbes mous : un do_now qui commence par ca n'est pas une action concrete.
VERBES_VAGUES = [
    "reflechis", "explore", "envisage", "considere", "pense a", "positionne-toi",
    "definis ta strategie", "etudie", "analyse la possibilite", "vois si",
]


def _fold(s: str) -> str:
    """minuscule + sans accents, pour comparer robustement."""
    s = (s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _mot_present(mot: str, texte_folde: str) -> bool:
    """vrai si `mot` (deja folde) apparait comme mot/expression entier."""
    pad = f" {texte_folde} "
    return f" {mot} " in pad or pad.startswith(f" {mot} ") or pad.endswith(f" {mot} ")


def _insight_repete_pourquoi(insight: str, pourquoi: str) -> bool:
    """vrai si insight est du remplissage : quasi-egal a pourquoi_maintenant apres
    normalisation, ou l'un contenu dans l'autre (cas trivial, pas de similarite floue)."""
    fi, fp = _fold(insight).strip(), _fold(pourquoi).strip()
    if not fi or not fp:
        return False
    if fi == fp:
        return True
    return fi in fp or fp in fi


def juger_radar(radar: dict) -> dict:
    problemes = []

    def bloc(move, regle, extrait=""):
        problemes.append({"move": move, "regle": regle, "extrait": (extrait or "")[:80], "bloquant": True})

    if not isinstance(radar, dict):
        return {"go": False, "problemes": [{"move": "-", "regle": "radar non-dict", "extrait": "", "bloquant": True}], "score": 0}

    moves = radar.get("moves", []) or []
    # Jour calme (moves=[]) = GO : brief silencieux legitime.
    for idx, m in enumerate(moves):
        if not isinstance(m, dict):
            bloc(f"move#{idx+1}", "move non-dict")
            continue
        nom = m.get("projet") or (m.get("title", "") or "")[:30] or f"move#{idx+1}"
        title = (m.get("title") or "").strip()
        pourquoi = (m.get("pourquoi_maintenant") or "").strip()
        do_now = (m.get("do_now") or "").strip()
        insight = (m.get("insight") or "").strip()
        est_star = (m.get("rank") == "star")

        # 1. title present + scannable
        if not title:
            bloc(nom, "title vide")
        elif len(title) > TITLE_MAX:
            bloc(nom, f"title trop long ({len(title)}>{TITLE_MAX} car, pas scannable 3s)", title)

        # 2. pourquoi present
        if not pourquoi:
            bloc(nom, "pourquoi_maintenant vide")
        elif len(pourquoi) > POURQUOI_MAX:
            bloc(nom, f"pourquoi trop long ({len(pourquoi)}>{POURQUOI_MAX})", pourquoi)

        # 3. do_now present + concret
        if not do_now:
            bloc(nom, "do_now vide (aucune action concrete)")
        else:
            if len(do_now) > DO_NOW_MAX:
                bloc(nom, f"do_now trop long ({len(do_now)}>{DO_NOW_MAX})", do_now)
            fdn = _fold(do_now)
            for vague in VERBES_VAGUES:
                if fdn.startswith(_fold(vague)):
                    bloc(nom, f"do_now commence par un verbe mou : '{vague}'", do_now)
                    break

        # 3b. insight (SPEC-INSIGHT-2B) : optionnel SAUF pour le move star ou le
        # prompt l'exige. Retro-compatibilite : un radar sans insight (ancien format,
        # jours calmes, moves non-star) passe exactement comme avant.
        if est_star and not insight:
            bloc(nom, "insight vide (obligatoire sur le move star)")
        elif insight:
            if len(insight) > INSIGHT_MAX:
                bloc(nom, f"insight trop long ({len(insight)}>{INSIGHT_MAX} car)", insight)
            if pourquoi and _insight_repete_pourquoi(insight, pourquoi):
                bloc(nom, "insight repete pourquoi_maintenant (remplissage, pas de lecture strategique)", insight)

        # 4. phrases creuses + jargon brut sur les champs visibles
        for champ, val in (("title", title), ("pourquoi", pourquoi), ("do_now", do_now), ("insight", insight)):
            f = _fold(val)
            for creux in PHRASES_CREUSES:
                if _fold(creux) in f:
                    bloc(nom, f"phrase creuse dans {champ} : '{creux}'", val)
            for jar in JARGON_BRUT:
                if _mot_present(_fold(jar), f):
                    bloc(nom, f"jargon brut non traduit dans {champ} : '{jar}'", val)

    nb_bloq = sum(1 for p in problemes if p["bloquant"])
    score = max(0, 100 - 25 * nb_bloq)
    return {"go": nb_bloq == 0, "problemes": problemes, "score": score}


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
    v = juger_radar(radar)
    if v["go"]:
        print(f"GO - radar clair (score {v['score']}/100).")
        return 0
    print(f"NO-GO - radar pas assez clair (score {v['score']}/100). Problemes :")
    for pb in v["problemes"]:
        if pb["bloquant"]:
            ex = (pb["extrait"] or "").encode("ascii", "replace").decode("ascii")
            print(f"  [{pb['move']}] {pb['regle']}  ->  {ex}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
