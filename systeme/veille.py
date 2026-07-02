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
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VEILLE_ROOT = HERE.parent
DATA = VEILLE_ROOT / "data"
PY = sys.executable

# --- Sanitizer anti-injection (defense en profondeur, en plus du pare-feu dans
# prompt_analyse_auto.md) : les titres/resumes de signaux viennent d'inconnus sur
# internet (Reddit/HN/GitHub/YouTube) et entrent chaque matin dans un claude -p
# headless. On les neutralise AVANT qu'ils atteignent le prompt : caracteres de
# controle retires (empeche un titre de mimer un nouveau bloc/instruction via des
# retours-ligne ou des caracteres invisibles), longueur plafonnee.
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
TITRE_MAX = 220


def _assainir(texte: str) -> str:
    """Neutralise un titre/resume externe : retire les caracteres de controle
    (dont \\n\\r qui simulent un saut de bloc), collapse les espaces, tronque.
    Ne change JAMAIS le sens d'un titre legitime — coupe juste ce qui n'a rien
    a faire dans un titre humain."""
    t = _CTRL.sub(" ", str(texte or ""))
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > TITRE_MAX:
        t = t[:TITRE_MAX].rstrip() + "…"
    return t


def step(label: str, script: str) -> int:
    """Lance une etape, renvoie son code retour brut (0=ok, autre=a interpreter)."""
    print(f"\n>>> {label}")
    r = subprocess.run([PY, str(HERE / script)], cwd=str(VEILLE_ROOT))
    return r.returncode


def prepare_analyse() -> int:
    """Compacte signaux_frais.json en _pour_analyse.json (titre/url/canal/projet/date)."""
    src = DATA / "signaux_frais.json"
    if not src.exists():
        print("  (pas de signaux_frais.json — rien a preparer)")
        return 0
    d = json.loads(src.read_text(encoding="utf-8"))
    # signaux_frais.json est DEJA trie par score (collecte_signaux). On propage le
    # score "s" et on garde l'ordre (le mieux score d'abord) pour le Claude du matin.
    # Titre = texte ecrit par un inconnu sur internet -> assaini (voir _assainir).
    items = [{"t": _assainir(s["titre"]), "u": s["url"], "c": s["canal"], "p": s["projet"],
              "d": s.get("date", ""), "s": s.get("score", 0)}
             for s in d.get("signaux_frais", [])]
    (DATA / "_pour_analyse.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return len(items)


def lire_incidents() -> list[dict]:
    """Relit signaux_frais.json pour savoir si un canal vital est en panne."""
    p = DATA / "signaux_frais.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("incidents", []) or []
    except Exception:
        return []


def ecrire_marqueur(n: int, incidents: list[dict]) -> None:
    """Pose data/_a_analyser.flag : signal pour la routine Claude qu'il y a du grain
    a moudre (analyse -> radar). Contient le minimum pour decider sans relire tout.
    Le .bat / la routine lisent ce marqueur ; ils le suppriment apres analyse."""
    marqueur = {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "nb_frais": n,
        "panne": bool(incidents),
        "incidents": incidents,
        "a_analyser": n > 0,            # True => un Claude doit produire le radar
    }
    (DATA / "_a_analyser.flag").write_text(
        json.dumps(marqueur, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    print("=== VEILLE - pipeline de collecte ===")
    if step("1/3 Scan de l'atelier", "scan_atelier.py") != 0:
        print("ECHEC au scan de l'atelier. Stop.")
        return 1

    # COUCHE 2 : recalcule l'overlay de scoring depuis les 'paye' AVANT la collecte,
    # pour que les signaux soient scores avec ce qu'on a appris. Jamais bloquant.
    step("1b/3 Apprentissage (overlay des projets qui paient)", "apprends_poids.py")

    # collecte_signaux : 0 = ok, 2 = PANNE (mais on continue : la panne doit etre
    # signalee, pas avalee), 1 = echec dur (atelier manquant) -> stop.
    rc = step("2/3 Collecte des signaux frais", "collecte_signaux.py")
    if rc == 1:
        print("ECHEC dur a la collecte. Stop.")
        return 1

    print("\n>>> 3/3 Preparation pour l'analyse")
    n = prepare_analyse()
    incidents = lire_incidents()
    ecrire_marqueur(n, incidents)
    print(f"  {n} signaux frais prets pour l'analyse -> data/_pour_analyse.json")
    print(f"  marqueur ecrit -> data/_a_analyser.flag (a_analyser={n > 0})")

    print("\n=== COLLECTE TERMINEE ===")
    if incidents:
        noms = ", ".join(i["canal"] for i in incidents)
        print(f"!! PANNE : canal(aux) muet(s) -> {noms}")
        print("   (ce n'est PAS un jour calme : un canal vital a echoue)")
    if n == 0 and not incidents:
        print("Rien de neuf aujourd'hui -> brief silencieux (c'est voulu).")
    elif n > 0:
        print(f"{n} signaux neufs. Etape suivante (analyse -> radar) :")
        print("  un Claude lit data/_pour_analyse.json + systeme/PROMPT_RADAR.md")
        print("  et ecrit briefs/AAAA-MM-JJ_radar.md au format valide.")
    # Code retour : 2 si panne (le .bat declenche l'alerte), 0 sinon.
    return 2 if incidents else 0


if __name__ == "__main__":
    sys.exit(main())
