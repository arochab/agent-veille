#!/usr/bin/env python3
"""
config_projets.py — Loader de data/projets.json (audit Fable, reco #4).

PROBLEME : la config projet (tiers, alias, requetes, noms d'affichage) etait
dupliquee dans 5 fichiers (scoring.py, collecte_signaux.py, executer_move.py,
suivi_go.py, prompt_analyse_auto.md). Ajouter un projet = 5 endroits a toucher,
et un oubli = incoherence silencieuse (ex: un alias present dans executer_move
mais pas dans suivi_go -> le nom d'affichage ne matche pas).

MIGRATION PRUDENTE : ce module ne remplace RIEN de force. Il expose juste
charger_projets() qui lit data/projets.json. CHAQUE module appelant garde son
propre dict fige en repli (fallback) si le chargement echoue -> zero risque
de regression meme si projets.json est absent, corrompu, ou mal rempli.
"""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
FICHIER = DATA / "projets.json"

_cache = None  # cache process-local : on ne relit le fichier qu'une fois par run


def charger_projets() -> dict:
    """Renvoie {slug: {nom_affichage, tier, alias, requetes_veille, ramp}} ou {}
    si le fichier est absent/corrompu (jamais d'exception remontante — chaque
    appelant doit alors utiliser son propre repli fige)."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        d = json.loads(FICHIER.read_text(encoding="utf-8"))
        _cache = d.get("projets", {}) or {}
    except Exception:
        _cache = {}
    return _cache


def index_alias() -> dict:
    """{alias_normalise: slug_canonique} pour TOUS les projets. Inclut le slug
    lui-meme comme alias de lui-meme. Normalisation: lower/strip uniquement
    (chaque appelant applique ensuite sa propre normalisation d'espaces/tirets
    si besoin, pour rester compatible avec son ancien comportement)."""
    projets = charger_projets()
    out = {}
    for slug, info in projets.items():
        out[slug.strip().lower()] = slug
        for a in info.get("alias", []) or []:
            out[str(a).strip().lower()] = slug
    return out


def tier_de(slug: str) -> int | None:
    """Tier (1/2/3) du projet, ou None si projets.json absent/projet inconnu —
    l'appelant (scoring.py) doit alors utiliser sa propre table TIER1/2/3 figee."""
    projets = charger_projets()
    info = projets.get(slug)
    return info.get("tier") if info else None


def nom_affichage_de(slug: str) -> str | None:
    """Nom produit ('BrandPulse') du slug technique ('serp-scraper'), ou None
    si absent — l'appelant (suivi_go.py) garde alors son propre NOMS_AFFICHAGE."""
    projets = charger_projets()
    info = projets.get(slug)
    return info.get("nom_affichage") if info else None


def requetes_de(slug: str) -> list | None:
    """Requetes de veille du projet, ou None si absent — l'appelant
    (collecte_signaux.py) garde alors son propre REQUETES_PAR_PROJET."""
    projets = charger_projets()
    info = projets.get(slug)
    return info.get("requetes_veille") if info else None
