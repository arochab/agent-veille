#!/usr/bin/env python3
"""
_setup_reddit.py — Écrit le cookie reddit_session (compte jetable) dans le
credential rdt-cli, au bon endroit, puis vérifie la connexion.

Usage : python systeme/_setup_reddit.py "<valeur_du_cookie_reddit_session>"

Le cookie reste 100% LOCAL (~/.config/rdt-cli/credential.json). Jamais sur GitHub.
Compte JETABLE uniquement (Round_Leg_82) — jamais le compte perso d'Adam.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "rdt-cli"
CRED = CONFIG_DIR / "credential.json"


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("Usage: python systeme/_setup_reddit.py \"<reddit_session>\"")
        return 1
    session = sys.argv[1].strip()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cred = {
        "cookies": {"reddit_session": session},
        "source": "manual-paste",
        "username": "Round_Leg_82",
        "modhash": None,
        "saved_at": time.time(),
        "last_verified_at": None,
    }
    CRED.write_text(json.dumps(cred, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK - credential ecrit : {CRED}")
    print("Teste maintenant : rdt whoami  puis  rdt search \"...\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
