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

DEUX NIVEAUX de protection :
  - VITAUX (ATTENDUS)      : alteration => ok=False, tout est bloque (halt inchange).
  - SENTINELLES            : alteration => AVERTISSEMENT seulement, ok/halt intacts.
    POURQUOI : les organes du pipeline (collecte, livraison, suivi...) changent plus
    souvent que le noyau ; les bloquer a chaque evolution voulue tuerait le systeme.
    Mais une alteration NON voulue doit quand meme se VOIR -> alerte sans frein.

Usage :
  python systeme/immunite.py            -> verifie, affiche le verdict, exit 0/1
  python systeme/immunite.py --ref-now  -> imprime les hashes actuels (pour mettre a
                                            jour ATTENDUS apres un changement VOULU)
  python systeme/immunite.py --signer   -> imprime les blocs ATTENDUS + SENTINELLES
                                            complets, prets a coller dans ce fichier
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
    "tests.py":        "204618500c98d0baf79354415003a0880bd454ff2d2eb938eb8ffb7e947a5ef3",
    "jury_clarte.py":  "4bc0fb626df5c47303a3f9abf56087acc9e714bb175985fd86c52410fdc3b4dc",
    "scoring.py":      "6f1d30de2bb60c42c6314b9b0b7942372f0be47838a05a043a85c487c3249a5a",
    "auto_sources.py": "e6d8085a824eca3e67f58e7788d36f31cc2f3625facf3ecb18417be8565cb162",
    "feedback.py":     "6f1ef69c63ce593fd95ff471fcf7a1f18e10e3c20e4c0decee892434544e31e6",
    "apprends_poids.py": "0d9b43507220d58e637c2096e682df92e50aed2fb74e824d8e2a9c1f97e289db",
}

# ── SENTINELLES — surveillance SANS blocage. CODES EN DUR aussi (jamais data/). ──
# Une alteration ici ne coupe RIEN : elle est remontee dans 'alteres_sentinelle'
# (verifier) et affichee en avertissement (main). Re-signature : --signer.
SENTINELLES = {
    "executer_move.py": "4f3f57a7ee83bbf0eca05cc0d19b99ba7b92dc703e43e994adc12ed6a06bbd83",
    "envoyer_telegram.py": "49942786cf7b37c8c7509124e397329c2848289aa8edee1a878a18c3cc4e586c",
    "collecte_signaux.py": "23aa79b05c1be28e921aa3dd2defbcbb95cfb93d3b8c1ecbf3601dd072693ea0",
    "suivi_go.py": "18663d703e50891bec30ca04697b8dd1b2fbe7355435832072b1985a810f2ab5",
    "digest_roi.py": "1f15ec301aae47f421ba6463851621929879388259b3a75611beaf90c750756f",
    "atomic_io.py": "c6af95a6d098c0f24ca77ba72b7946e39b620dd4b0ec74b00704328c6137b06c",
    "config_projets.py": "0adcaeaf70e80e3f9c3c70501928755115a2fa31568c4d52b345dbc9ddd25f0d",
}


def _sha(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return ""


def halt_actif() -> bool:
    """Kill-switch mou : si data/HALT.flag existe, l'auto-modif est gelee."""
    return HALT.exists()


def _sentinelles_alterees() -> list:
    """Passe en revue les SENTINELLES : alteree OU manquante = a signaler.
    POURQUOI une seule liste : c'est de l'information (pas un frein), inutile de
    distinguer — dans les deux cas Adam doit regarder puis re-signer si voulu."""
    alterees = []
    for nom, attendu in SENTINELLES.items():
        p = SYS / nom
        if not p.exists() or _sha(p) != attendu:
            alterees.append(nom)
    return alterees


def verifier() -> dict:
    """Verifie l'integrite des organes vitaux + le kill-switch.
    Retourne {ok, halt, alteres:[...], manquants:[...], alteres_sentinelle:[...]}.
    ok=True => on a le DROIT d'auto-modifier. ok=False => on ne touche a rien.
    COMPATIBILITE : ok/halt ne dependent QUE des vitaux et du kill-switch ;
    'alteres_sentinelle' est purement informatif (alerte sans blocage)."""
    if halt_actif():
        return {"ok": False, "halt": True, "alteres": [], "manquants": [],
                "alteres_sentinelle": _sentinelles_alterees(),
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
            "alteres_sentinelle": _sentinelles_alterees(),
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
    if "--signer" in sys.argv:
        # Blocs COMPLETS prets a coller : zero friction de re-signature (la friction
        # decourage de proteger les fichiers -> on la reduit au copier-coller).
        print("# Blocs a coller tels quels dans systeme/immunite.py (changement VOULU) :")
        print("ATTENDUS = {")
        for nom in ATTENDUS:
            print(f'    "{nom}": "{_sha(SYS / nom)}",')
        print("}")
        print("")
        print("SENTINELLES = {")
        for nom in SENTINELLES:
            print(f'    "{nom}": "{_sha(SYS / nom)}",')
        print("}")
        return 0
    v = verifier()
    # AVERTISSEMENT sentinelle : visible mais SANS effet sur le verdict ni l'exit code
    # (un caller qui teste l'exit code ne doit pas se faire freiner par une sentinelle).
    if v.get("alteres_sentinelle"):
        print(f"IMMUNITE AVERTISSEMENT - sentinelles alterees (sans blocage) : {v['alteres_sentinelle']}")
        print("  -> Si ce changement est VOULU : python systeme/immunite.py --signer,")
        print("     puis colle le bloc SENTINELLES dans ce fichier (a la main).")
    if v["ok"]:
        print("IMMUNITE OK - organes vitaux intacts, pas de HALT. Auto-modif autorisee.")
        return 0
    if v["halt"]:
        print("IMMUNITE - HALT.flag present : auto-modif GELEE (la livraison continue).")
        return 1
    print(f"IMMUNITE ALERTE - alteres={v['alteres']} manquants={v['manquants']}")
    print("  -> Si ce changement est VOULU : python systeme/immunite.py --signer,")
    print("     puis colle les nouveaux hashes dans ATTENDUS (a la main).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
