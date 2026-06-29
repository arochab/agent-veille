#!/usr/bin/env python3
"""
scan_atelier.py — Découvre TOUS les projets d'Adam dans `Adam CHABBI Pro`
et produit un snapshot JSON propre, toujours à jour.

C'est la fondation de la veille agnostique : la veille ne connaît pas une liste
figée de 3 projets, elle re-scanne l'atelier à chaque passage. Ajoute un projet
demain → il apparaît automatiquement.

Lecture seule. N'écrit QUE dans agent-earch-veille/data/. Zéro modif ailleurs.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# L'atelier = le dossier parent de agent-earch-veille
HERE = Path(__file__).resolve().parent          # .../agent-earch-veille/systeme
VEILLE_ROOT = HERE.parent                        # .../agent-earch-veille
ATELIER = VEILLE_ROOT.parent                     # .../Adam CHABBI Pro
OUT = VEILLE_ROOT / "data" / "atelier.json"

# Dossiers à ignorer (pas des projets)
SKIP = {"agent-earch-veille", "archive", "_SECURITY", ".git", "node_modules", "__pycache__"}

# Fichiers de contexte lus en priorité pour décrire le projet
DOC_FILES = ["PROJECT-STATUS.md", "CONTEXT.md", "README.md", "CLAUDE.md"]


def first_meaningful_lines(path: Path, n: int = 6) -> str:
    """Renvoie les n premières lignes non vides d'un fichier, nettoyées."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # enlève les commentaires HTML et titres markdown vides
    out = []
    for ln in lines:
        if ln.startswith("<!--") or ln.startswith("-->"):
            continue
        out.append(re.sub(r"^#+\s*", "", ln))
        if len(out) >= n:
            break
    return " · ".join(out)


def git_last_commit(proj: Path) -> str | None:
    """Date ISO du dernier commit, ou None si pas un repo git."""
    if not (proj / ".git").exists():
        return None
    try:
        r = subprocess.run(
            ["git", "-C", str(proj), "log", "-1", "--format=%cI"],
            capture_output=True, text=True, timeout=10,
        )
        out = r.stdout.strip()
        return out or None
    except Exception:
        return None


def detect_stack(proj: Path) -> list[str]:
    """Devine la stack à partir des fichiers présents."""
    stack = []
    checks = {
        "package.json": "node",
        "svelte.config.js": "svelte",
        "next.config.ts": "next",
        "next.config.js": "next",
        "vite.config.ts": "vite",
        "requirements.txt": "python",
        "pyproject.toml": "python",
        "render.yaml": "render",
        "vercel.json": "vercel",
        "supabase": "supabase",
    }
    for f, label in checks.items():
        if (proj / f).exists() and label not in stack:
            stack.append(label)
    return stack


def newest_mtime(proj: Path) -> str:
    """Date de modif la plus récente (profondeur 2), comme proxy d'activité."""
    newest = 0.0
    try:
        for root, dirs, files in os.walk(proj):
            # ne descend pas dans les gros dossiers
            depth = len(Path(root).relative_to(proj).parts)
            if depth >= 2:
                dirs[:] = []
            dirs[:] = [d for d in dirs if d not in {"node_modules", ".git", "dist", "__pycache__"}]
            for fn in files:
                try:
                    m = (Path(root) / fn).stat().st_mtime
                    if m > newest:
                        newest = m
                except OSError:
                    continue
    except Exception:
        pass
    if not newest:
        return ""
    return datetime.fromtimestamp(newest, tz=timezone.utc).date().isoformat()


def scan() -> dict:
    projets = []
    for entry in sorted(ATELIER.iterdir()):
        if not entry.is_dir() or entry.name in SKIP or entry.name.startswith("_"):
            continue
        doc = ""
        doc_source = None
        for df in DOC_FILES:
            p = entry / df
            if p.exists():
                doc = first_meaningful_lines(p)
                doc_source = df
                break
        projets.append({
            "nom": entry.name,
            "chemin": str(entry),
            "resume": doc,
            "doc_source": doc_source,
            "stack": detect_stack(entry),
            "git": bool((entry / ".git").exists()),
            "dernier_commit": git_last_commit(entry),
            "derniere_activite": newest_mtime(entry),
            "a_doc": doc_source is not None,
        })
    return {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "atelier": str(ATELIER),
        "nb_projets": len(projets),
        "projets": projets,
    }


def main() -> int:
    snap = scan()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    # Affichage console en ASCII pur (Windows cp1252-safe)
    def safe(s: str) -> str:
        return s.encode("ascii", "replace").decode("ascii")
    print(f"OK - {snap['nb_projets']} projets scannes -> {OUT}")
    for p in snap["projets"]:
        flag = "doc" if p["a_doc"] else "-"
        print(f"  {safe(p['nom']):<28} [{flag}] activite={p['derniere_activite'] or '?'} stack={','.join(p['stack']) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
