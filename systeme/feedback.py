#!/usr/bin/env python3
"""
feedback.py — Archivage du radar + feedback IDEMPOTENT (etape 3).

POURQUOI (faille red-team) : aujourd'hui data/radar.json reste apres envoi. Si on
le relisait pour en deduire "ce signal est devenu un move" (label positif), on le
recompterait a chaque run -> apprentissage fausse par double-comptage. PARADE :
  1. Apres envoi, on ARCHIVE le radar date dans briefs/ (et on libere radar.json).
  2. Chaque move recoit un ID STABLE (projet + titre + date). Un registre
     data/feedback_vu.json garde les IDs deja consommes -> jamais deux fois.

Sert de socle a la COUCHE 2 (Adam tape "paye <projet>" depuis Telegram -> on
enregistre UN event, idempotent, qui fera monter ce type de signal).

Stdlib pure, robuste Windows, deterministe (la date est passee/derivee, pas de
hasard). N'ecrit que dans data/ et briefs/.

CLI :
  python systeme/feedback.py --archive   # archive radar.json -> briefs/, libere radar.json
  python systeme/feedback.py --enregistrer <type> <projet> [montant]   # log 1 event idempotent
"""
from __future__ import annotations
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ecriture atomique (audit Fable, P1-4) : feedback_vu.json ne doit jamais etre
# tronque par un crash mid-write (un event 'paye' marque vu mais perdu ne
# reviendra jamais).
try:
    from atomic_io import write_json_atomic
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from atomic_io import write_json_atomic

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BRIEFS = ROOT / "briefs"
RADAR = DATA / "radar.json"
VU = DATA / "feedback_vu.json"          # registre des events deja consommes
EVENTS = DATA / "feedback_events.jsonl"  # journal append-only des feedbacks (audit)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def move_id(projet: str, titre: str, date: str) -> str:
    """ID stable d'un move : meme (projet,titre,date) -> meme id. Pas de hasard."""
    base = f"{(projet or '').strip().lower()}|{(titre or '').strip().lower()}|{date}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _load(p: Path, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def archiver_radar() -> bool:
    """Archive data/radar.json -> briefs/AAAA-MM-JJ_radar.json puis libere radar.json.
    Idempotent : si radar.json absent, ne fait rien. Evite le re-spam et le double-comptage."""
    if not RADAR.exists():
        return False
    try:
        radar = json.loads(RADAR.read_text(encoding="utf-8"))
    except Exception:
        return False
    date = radar.get("date") or _today()
    BRIEFS.mkdir(parents=True, exist_ok=True)
    cible = BRIEFS / f"{date}_radar.json"
    # On annote chaque move de son id stable (utile pour la couche 2).
    for m in radar.get("moves", []) or []:
        m["_id"] = move_id(m.get("projet", ""), m.get("title", ""), date)
    # ANTI-ORPHELIN : si un radar du jour existe DEJA (2e collecte le meme jour), on NE
    # l'ecrase PAS -> ses _id (donc les go lances dessus) survivent. On archive la nouvelle
    # version a part avec un suffixe horaire. Le suivi retrouve un go du matin meme apres
    # une regeneration l'apres-midi. (Defense en profondeur : le snapshot du go reste le
    # 1er rempart, mais on ne detruit plus la source non plus.)
    if cible.exists():
        try:
            heure = datetime.now(timezone.utc).strftime("%H%M%S")
        except Exception:
            heure = "rev"
        cible = BRIEFS / f"{date}_{heure}_radar.json"
    write_json_atomic(cible, radar)
    # Libere radar.json : il a ete livre + archive. Plus jamais recompte.
    try:
        RADAR.unlink()
    except Exception:
        pass
    return True


def enregistrer_event(type_event: str, projet: str, montant: str = "", date: str = "") -> dict:
    """Enregistre UN feedback, idempotent. type_event ex: 'paye','fait','utile'.
    Retourne {ok, deja_vu, id}. Le meme event (meme type+projet+date) n'est compte qu'une fois."""
    date = date or _today()
    eid = hashlib.sha1(f"{type_event}|{projet}|{montant}|{date}".encode("utf-8")).hexdigest()[:16]
    vu = set(_load(VU, []))
    if eid in vu:
        return {"ok": True, "deja_vu": True, "id": eid}
    DATA.mkdir(parents=True, exist_ok=True)
    # ORDRE CORRIGE (audit Fable, P2) : le JOURNAL (source de verite, append-only)
    # s'ecrit AVANT le registre "deja vu". Si le process meurt entre les deux,
    # l'event reste journalise -> au pire il sera traite une 2e fois (idempotent,
    # sans consequence), jamais PERDU. L'ancien ordre pouvait marquer un event
    # 'paye' comme vu puis crasher avant l'append : perdu pour toujours.
    rec = {"id": eid, "type": type_event, "projet": projet, "montant": montant, "date": date}
    with EVENTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    vu.add(eid)
    write_json_atomic(VU, sorted(vu))
    return {"ok": True, "deja_vu": False, "id": eid}


def main() -> int:
    if "--archive" in sys.argv:
        ok = archiver_radar()
        print("radar archive + libere." if ok else "pas de radar.json a archiver.")
        return 0
    if "--enregistrer" in sys.argv:
        i = sys.argv.index("--enregistrer")
        args = sys.argv[i + 1:]
        if len(args) < 2:
            print("Usage: --enregistrer <type> <projet> [montant]")
            return 2
        type_event, projet = args[0], args[1]
        montant = args[2] if len(args) > 2 else ""
        r = enregistrer_event(type_event, projet, montant)
        print(f"event {'deja vu (ignore)' if r['deja_vu'] else 'enregistre'} id={r['id']}")
        return 0
    print("Usage: --archive | --enregistrer <type> <projet> [montant]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
