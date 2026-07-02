#!/usr/bin/env python3
"""
immunite.py — LE GARDIEN. Verifie que les organes vitaux n'ont pas ete alteres
en douce avant d'autoriser une auto-modification.

POURQUOI (faille reine du red-team) : un systeme qui s'auto-modifie pourrait, par
erreur ou derive, reecrire le fichier de hashes cense le surveiller -> le gardien
effacerait ses propres regles. PARADE : les hashes attendus sont CODES EN DUR dans
CE module (jamais dans data/ que le systeme peut ecrire). Pour les changer, il faut
editer ce fichier a la main (Adam), pas un process automatique.

Regle d'or : AUCUNE auto-amelioration ne s'applique si verifier()['ok'] est False.
Et le kill-switch : si data/HALT.flag existe -> tout est gele (sauf la livraison).

Usage :
  python systeme/immunite.py            -> verifie, affiche le verdict, exit 0/1
  python systeme/immunite.py --ref-now  -> imprime les hashes actuels (pour mettre a
                                            jour ATTENDUS apres un changement VOULU)
"""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path

SYS = Path(__file__).resolve().parent
ROOT = SYS.parent
HALT = ROOT / "data" / "HALT.flag"

# ── HASHES ATTENDUS — CODES EN DUR. Ne JAMAIS lire ca depuis data/. ──
# Pour les regenerer apres un changement VOULU : python systeme/immunite.py --ref-now
# puis coller les valeurs ici a la main.
ATTENDUS = {
    "tests.py":        "e041d024a83662d7b933699abc2197e484bf75d91cd2c0279cdd35ecc0cc2e07",
    "jury_clarte.py":  "b92166d23e2c7f6a6929ac53f9c9d8c1a8f8d27364b58ed9324f1ce75366da99",
    "scoring.py":      "6f1d30de2bb60c42c6314b9b0b7942372f0be47838a05a043a85c487c3249a5a",
    "auto_sources.py": "e6d8085a824eca3e67f58e7788d36f31cc2f3625facf3ecb18417be8565cb162",
    "feedback.py":     "6f1ef69c63ce593fd95ff471fcf7a1f18e10e3c20e4c0decee892434544e31e6",
    "apprends_poids.py": "0d9b43507220d58e637c2096e682df92e50aed2fb74e824d8e2a9c1f97e289db",
}


def _sha(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return ""


def halt_actif() -> bool:
    """Kill-switch mou : si data/HALT.flag existe, l'auto-modif est gelee."""
    return HALT.exists()


def verifier() -> dict:
    """Verifie l'integrite des organes vitaux + le kill-switch.
    Retourne {ok, halt, alteres:[...], manquants:[...]}.
    ok=True => on a le DROIT d'auto-modifier. ok=False => on ne touche a rien."""
    if halt_actif():
        return {"ok": False, "halt": True, "alteres": [], "manquants": [],
                "raison": "HALT.flag present : auto-modif gelee par Adam."}
    alteres, manquants = [], []
    for nom, attendu in ATTENDUS.items():
        p = SYS / nom
        if not p.exists():
            manquants.append(nom); continue
        if _sha(p) != attendu:
            alteres.append(nom)
    ok = not alteres and not manquants
    return {"ok": ok, "halt": False, "alteres": alteres, "manquants": manquants,
            "raison": "" if ok else "organes vitaux alteres/manquants"}


def exiger_sain() -> None:
    """A appeler en tete de tout script d'auto-modification.
    Leve SystemExit si le systeme n'est pas sain -> rien ne s'applique."""
    v = verifier()
    if not v["ok"]:
        msg = "[IMMUNITE] BLOQUE - "
        if v["halt"]:
            msg += "HALT.flag present (auto-modif gelee)."
        else:
            msg += f"alteres={v['alteres']} manquants={v['manquants']}"
        print(msg)
        raise SystemExit(3)


def main() -> int:
    if "--ref-now" in sys.argv:
        print("# Hashes actuels (a coller dans ATTENDUS apres un changement VOULU) :")
        for nom in ATTENDUS:
            print(f'    "{nom}": "{_sha(SYS / nom)}",')
        return 0
    v = verifier()
    if v["ok"]:
        print("IMMUNITE OK - organes vitaux intacts, pas de HALT. Auto-modif autorisee.")
        return 0
    if v["halt"]:
        print("IMMUNITE - HALT.flag present : auto-modif GELEE (la livraison continue).")
        return 1
    print(f"IMMUNITE ALERTE - alteres={v['alteres']} manquants={v['manquants']}")
    print("  -> Si ce changement est VOULU : python systeme/immunite.py --ref-now,")
    print("     puis colle les nouveaux hashes dans ATTENDUS (a la main).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
