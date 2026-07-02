@echo off
REM lancer_move.bat - relais lance par executer_move.py (via start cmd /k).
REM %1 = dossier projet (absolu)   %2 = fichier prompt UTF-8 (absolu, 1 ligne)
REM Se place dans le projet, lit le prompt, lance Claude Code interactif en mode plan.
chcp 65001 >nul
cd /d %1
title The Wire - move en cours (%~nx1)
REM Lecture robuste du prompt (accents OK) via PowerShell ReadAllText.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "[IO.File]::ReadAllText('%~2')"`) do set "MOVE=%%P"
if not defined MOVE (
  echo [The Wire] Prompt introuvable ou vide : %~2
  echo Ouvre Claude Code manuellement dans ce dossier.
  claude --effort max --permission-mode plan
) else (
  claude --effort max --permission-mode plan "%MOVE%"
)
