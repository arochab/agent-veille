@echo off
REM ============================================================================
REM  demarrer_poller.bat — Lance le POLLER "go" de The Wire en continu.
REM
REM  Ecoute Telegram en permanence : quand Adam repond "go N" a son radar,
REM  ouvre Claude Code (VS Code) sur le bon projet avec le move.
REM
REM  Lance au demarrage de Windows (tache planifiee au logon). Fenetre cachee
REM  via le .vbs compagnon (poller_silencieux.vbs) -> pas de console visible.
REM  Un lockfile empeche deux instances.
REM ============================================================================
setlocal
set "ROOT=%~dp0.."
pushd "%ROOT%" >nul

set "PYEXE=python"
where py >nul 2>&1 && set "PYEXE=py"

REM --watch = long-poll continu. Journalise dans data\executer_move.log.
%PYEXE% systeme\executer_move.py --watch >> data\executer_move.log 2>&1

popd >nul
endlocal
