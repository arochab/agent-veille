#!/usr/bin/env python3
"""
hub_radar.py - Transforme le radar du matin en message pour le hub Second Cerveau.

Appele par lancer_veille.bat juste APRES l'envoi Telegram reussi (radar.json existe
encore, avant archivage). Lit data/radar.json, compose un message `digest` conforme
au contrat (corps micro-format, un bouton "Go move N" par move avec son move_id en
payload), et le depose via hub_outbox.emettre().

Le move_id de chaque bouton = MEME calcul qu'executer_move.traiter_go (move._id
sinon 'projet-title' normalise) : un clic PWA a l'identite exacte d'un go Telegram.
La resolution finale se fait cote poller (hub_actions), donc ici on n'a besoin que
de produire le bon move_id.

Zero dependance, ne leve jamais : emettre vers le hub ne doit pas faire echouer le
run du matin (le batch continue quoi qu'il arrive).

Usage : python systeme/hub_radar.py            (utilise data/radar.json)
        python systeme/hub_radar.py <chemin>   (radar explicite, pour test)
"""
from __future__ import annotations
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RADAR = ROOT / "data" / "radar.json"

try:
    import hub_outbox
except ImportError:
    sys.path.insert(0, str(HERE))
    import hub_outbox

# _norm identique a executer_move._norm (pas d'import croise pour rester autonome).
_ACCENTS = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")


def _norm(s: str) -> str:
    s = (s or "").strip().lower().translate(_ACCENTS)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s\-_]+", "", s)


def _mid(move: dict) -> str:
    """MEME identite qu'executer_move.traiter_go (ligne mid = ...)."""
    return move.get("_id") or f"{_norm(move.get('projet',''))}-{_norm(move.get('title',''))}"


def _moves_ordonnes(radar: dict) -> list:
    """Star d'abord, comme format_radar / traiter_go (go N == N-e move affiche)."""
    moves = radar.get("moves", []) or []
    if not moves:
        return []
    star = next((m for m in moves if m.get("rank") == "star"), moves[0])
    return [star] + [m for m in moves if m is not star]


def _corps_du_radar(radar: dict, moves: list) -> str:
    """Corps micro-format (texte brut) : la PWA echappe puis applique # / - / ** / `.
    On reste sobre : le detail complet vit dans la PWA de The Wire (action url)."""
    lignes = []
    head = radar.get("headline", "")
    if head:
        lignes.append(f"**{head}**")
        lignes.append("")
    for i, m in enumerate(moves, 1):
        etoile = "* " if m.get("rank") == "star" else ""
        projet = m.get("projet", "?")
        titre = m.get("title", "")
        meta = m.get("meta", "")
        ligne = f"- {etoile}{i}. `{projet}` : {titre}"
        if meta:
            ligne += f" ({meta})"
        lignes.append(ligne)
    skill = radar.get("skill_up", "")
    if skill:
        lignes.append("")
        lignes.append(f"# Skill up\n{skill}")
    return "\n".join(lignes)


def _actions_du_radar(moves: list, date_radar: str) -> list:
    """Un bouton 'Go move N' par move, avec confirmation (engage un plan)."""
    actions = []
    for i, m in enumerate(moves, 1):
        actions.append({
            "id": f"go{i}",
            "label": f"Go move {i}",
            "type": "module",
            "confirmer": True,
            "payload": {"move_id": _mid(m), "date_radar": str(date_radar)},
        })
    return actions[:hub_outbox.MAX_ACTIONS]


def emettre_radar(radar_path: Path = RADAR) -> str | None:
    """Lit le radar, compose le message digest, l'emet. Renvoie l'id ou None.
    Jour calme (0 move) : on emet quand meme un digest sobre 'rien de neuf' sans
    action (le hub montre que The Wire a tourne). Ne leve jamais."""
    try:
        radar = json.loads(Path(radar_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        date_radar = radar.get("date", "")
        moves = _moves_ordonnes(radar)

        if not moves:
            return hub_outbox.emettre(
                "Rien d'urgent aujourd'hui",
                corps="Jour calme - c'est du temps pour shipper.",
                type_="digest", priorite="info", tags=["radar"], fil="radar",
                resume_push="The Wire : jour calme, rien d'urgent",
            )

        star = moves[0]
        gain = ""
        try:
            # gain visible dans le titre du star (ex '~290 EUR'), best-effort.
            mgain = re.search(r"~?\s*([\d\s.,]+)\s*(?:EUR|€)", star.get("title", ""))
            if mgain:
                gain = mgain.group(0).strip()
        except Exception:
            pass

        titre = star.get("title", "Radar du jour")
        resume = f"Radar : {len(moves)} move(s)"
        if gain:
            resume += f", star {gain}"

        return hub_outbox.emettre(
            titre,
            corps=_corps_du_radar(radar, moves),
            type_="digest", priorite="normal",
            resume_push=resume, tags=["radar"], fil="radar",
            expire_le=None,
            actions=_actions_du_radar(moves, date_radar),
            data={"date": date_radar, "nb_moves": len(moves)},
        )
    except Exception:
        return None


if __name__ == "__main__":
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else RADAR
    mid = emettre_radar(p)
    print(f"radar emis vers le hub : {mid}" if mid else "aucun message emis (radar absent/vide/erreur)")
