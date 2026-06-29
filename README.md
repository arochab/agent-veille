# Veille — autonomous project-aware watch system

An agentic intelligence system that scans a portfolio of software projects, hunts
the web for fresh signals tied to each one, and turns them into **executable daily
briefs** — what to do, in numbered steps, ranked by gain over effort.

Built solo, agent-first. This repo is the **engine** (the strategy and project data
it operates on stay private).

---

## What it does

Every day, autonomously:

1. **Scans the workshop** — discovers every project in a directory, reads its state
   (README/status, git activity, stack), and builds a fresh snapshot. No hardcoded
   list: add a project tomorrow, it's picked up automatically (project-agnostic).
2. **Collects fresh signals** — derives targeted queries per project and pulls from
   GitHub + YouTube (extensible to Reddit/X/web). Keeps a memory of seen URLs so it
   only ever surfaces **what's new** — no daily repetition, silence when nothing's fresh.
3. **Generates an executable brief** — an LLM turns raw signals into ranked moves,
   each with numbered steps, copy-paste commands, a "done when" check, what it
   unlocks next, and the asymmetry rivals miss.

## Design principles

- **Project-agnostic & self-updating** — the system reads the portfolio live; it is
  never wired to a fixed list of projects.
- **Only the new** — a seen-URL memory guarantees signal/noise stays high; a quiet
  day produces a quiet brief, by design.
- **Executable over informative** — a brief that tells you *what to do in steps* beats
  one that tells you *what happened*.
- **Graceful degradation** — a dead channel is marked, never faked. No invented sources.
- **Robust on Windows** — ASCII-safe console, UTF-8 files, no fragile assumptions.

## Architecture

```
scan_atelier.py      ── discovers projects ──►  atelier.json (snapshot, private)
collecte_signaux.py  ── GitHub + YouTube ────►  signaux_frais.json (new only, private)
        │                  (seen-URL memory dedupes)
        ▼
veille.py            ── orchestrates the pipeline in one command
        ▼
PROMPT_RADAR.md      ── the spec an LLM follows to produce the executable brief
        ▼
briefs/AAAA-MM-JJ.md ── the daily radar (private)
```

## Stack

Python (standard library only — zero heavy deps), GitHub CLI, `yt-dlp`, and a
multi-channel collection layer (agent-reach). Designed to run unattended via a
scheduled cloud routine.

## Run it

```bash
python systeme/veille.py
```

Runs the full collection pipeline and prepares the day's signals for analysis.

---

*Engine is public; the portfolio data and strategic briefs it operates on are private.*
Built by **Adam Chabbi** — Lead Data Analyst & agentic product builder.
