#!/usr/bin/env python3
"""
apprends_poids.py — COUCHE 2 : le scoring APPREND de ce qui PAIE.

Quand un projet rapporte de l'argent (Adam tape "paye <projet>" depuis Telegram,
enregistre par feedback.py), ce projet merite de remonter dans le scoring : ses
futurs signaux comptent plus. Cette couche lit les events de feedback et ecrit un
OVERLAY EXTERNE (data/poids_overlay.json) que scoring.py consulte.

GARDE-FOUS (red-team) — non negociables :
  - scoring.py reste PUR et INTOUCHE : on n'ecrit qu'un fichier externe, lu de facon
    bornee. Le filet de tests prouve que le cash bat toujours la vanite, overlay ou pas.
  - Le bonus de tier est BORNE [0..TIER_BONUS_MAX] : un projet qui paie MONTE un peu,
    jamais ne descend, jamais au-dela d'une limite dure. On ne cree pas de super-tier.
  - Le panier ARGENT (POIDS_A dans scoring) n'est JAMAIS apprenable : la couche ne
    touche QUE le tier-bonus par projet. La vanite ne peut pas devenir du cash.
  - IDEMPOTENT : on lit le journal d'events deja-vus (feedback). Un meme "paye" ne
    compte qu'une fois (gere en amont par feedback.py).
  - GARDIEN : avant d'ecrire l'overlay, on verifie l'immunite (organes intacts, pas
    de HALT). Si le systeme n'est pas sain -> on n'ecrit rien.

BAREME (simple, deterministe, auditable) :
  bonus(projet) = min(TIER_BONUS_MAX, PAR_PAYE * nb_events_paye(projet))
  PAR_PAYE = 4  -> 1 paiement = +4, 3 paiements = +12 (plafond). Lineaire, plafonne.

Stdlib pure, robuste Windows. CLI :
  python systeme/apprends_poids.py            # recalcule l'overlay depuis les events
  python systeme/apprends_poids.py --montrer  # affiche l'overlay courant
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EVENTS = DATA / "feedback_events.jsonl"
OVERLAY = DATA / "poids_overlay.json"

PAR_PAYE = 4.0
TIER_BONUS_MAX = 12.0   # doit rester <= au TIER_BONUS_MAX de scoring.py


def _events() -> list[dict]:
    if not EVENTS.exists():
        return []
    out = []
    try:
        for ligne in EVENTS.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                out.append(json.loads(ligne))
            except Exception:
                continue
    except Exception:
        return []
    return out


def calculer_overlay() -> dict:
    """Recalcule l'overlay depuis TOUS les events 'paye'. Deterministe, pur."""
    paye_par_projet = {}
    for ev in _events():
        if (ev.get("type") or "").lower() == "paye":
            proj = (ev.get("projet") or "").strip().lower()
            if proj:
                paye_par_projet[proj] = paye_par_projet.get(proj, 0) + 1
    tier_bonus = {}
    for proj, n in sorted(paye_par_projet.items()):
        bonus = min(TIER_BONUS_MAX, PAR_PAYE * n)
        if bonus > 0:
            tier_bonus[proj] = bonus
    return {"tier_bonus": tier_bonus, "source": "apprends_poids", "nb_projets": len(tier_bonus)}


def appliquer() -> bool:
    """Ecrit data/poids_overlay.json, SI le systeme est sain (gardien). Sinon, rien."""
    # GARDIEN : pas d'auto-modif si organe altere ou HALT.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import immunite
        if not immunite.verifier()["ok"]:
            print("[apprends_poids] BLOQUE par immunite (organe altere ou HALT). Rien ecrit.")
            return False
    except Exception:
        pass
    overlay = calculer_overlay()
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        OVERLAY.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print("[apprends_poids] echec ecriture:", str(e)[:80])
        return False


def main() -> int:
    if "--montrer" in sys.argv:
        if OVERLAY.exists():
            print(OVERLAY.read_text(encoding="utf-8"))
        else:
            print("(pas d'overlay : aucun 'paye' enregistre pour l'instant)")
        return 0
    ok = appliquer()
    if ok:
        ov = calculer_overlay()["tier_bonus"]
        if ov:
            print("Overlay mis a jour. Projets qui ont paye (bonus de tier) :")
            for proj, b in ov.items():
                print(f"  {proj:24} +{b:.0f}")
        else:
            print("Overlay vide (aucun 'paye' encore). Tape 'paye <projet>' apres un vrai paiement.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
