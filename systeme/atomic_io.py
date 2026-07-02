#!/usr/bin/env python3
"""
atomic_io.py — Ecriture JSON atomique commune (audit Fable, P1-4).

PROBLEME : write_text(json.dumps(...)) direct sur un fichier existant n'est PAS
atomique. Un crash/coupure PENDANT l'ecriture laisse un JSON tronque -> le loader
(qui attrape toujours l'exception et retombe sur un defaut) efface silencieusement
toute la memoire : vu.json corrompu = re-flood de vieux signaux, go_traites.json
corrompu = double lancement d'un move, tg_offset.json corrompu = re-traitement
de vieux messages Telegram.

FIX : ecrire dans un fichier .tmp (meme dossier = meme volume, donc le
remplacement final est atomique sur Windows/NTFS et POSIX), puis Path.replace().
Si le process meurt avant le replace(), le fichier ORIGINAL reste intact —
seul le .tmp est perdu.

Utilisation (remplace un write_text(json.dumps(...)) existant) :
    from atomic_io import write_json_atomic
    write_json_atomic(CHEMIN, objet)
"""
from __future__ import annotations
import json
import os
from pathlib import Path


def write_json_atomic(chemin: Path, objet, *, indent: int = 2, ensure_ascii: bool = False) -> bool:
    """Ecrit `objet` en JSON dans `chemin` de facon atomique : jamais de fichier
    tronque en cas de crash/coupure pendant l'ecriture. Renvoie True si OK, False
    si l'ecriture a echoue (l'ancien fichier, s'il existait, reste intact dans
    tous les cas — jamais d'exception remontante, comme les autres modules du
    pipeline qui degradent proprement plutot que de planter la chaine du matin)."""
    p = Path(chemin)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # PID dans le nom du .tmp : deux process concurrents (ex. double lancement
        # accidentel du poller) n'ecrasent pas le meme fichier temporaire.
        tmp = p.with_suffix(p.suffix + f".tmp{os.getpid()}")
        tmp.write_text(
            json.dumps(objet, ensure_ascii=ensure_ascii, indent=indent),
            encoding="utf-8",
        )
        tmp.replace(p)  # atomique sur le meme volume (Windows NTFS + POSIX)
        return True
    except Exception:
        try:
            tmp.unlink(missing_ok=True)  # nettoie le .tmp orphelin si l'ecriture a rate
        except Exception:
            pass
        return False
