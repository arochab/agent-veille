@echo off
REM ============================================================================
REM  surveiller_poller.bat - Garde-fou anti-crash du poller "go" de The Wire.
REM
REM  POURQUOI (incident reel du 2026-07-02) : le poller (executer_move.py --watch)
REM  n'etait lance qu'a la main, sans tache planifiee -> un redemarrage/extinction
REM  du PC le tuait definitivement, sans que rien ne le relance. Verifie 2026-07-06 :
REM  aucun "go" perdu (Adam n'en avait pas tape), mais le risque etait reel.
REM
REM  Ce script est lance PERIODIQUEMENT (tache planifiee, toutes les 10 min) : il
REM  verifie si le PID du lockfile (data\executer_move.lock) est un vrai processus
REM  python.exe encore vivant. Si non (verrou perime ou absent) -> relance le
REM  poller en silencieux (poller_silencieux.vbs, pas de fenetre visible).
REM  Si le poller tourne deja : ne fait RIEN (idempotent, jamais de double instance
REM  -- le lock de executer_move.py refuserait de toute facon la 2e instance).
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=%~dp0.."
pushd "%ROOT%" >nul

set "LOCK=data\executer_move.lock"
set "LOG=data\surveiller_poller.log"

if not exist "%LOCK%" (
  echo [%date% %time%] lock absent - poller jamais demarre ou arrete proprement, relance.>> "%LOG%"
  goto :relancer
)

REM Extrait le PID du JSON (ligne '  "pid": 12345,') sans dependance externe.
REM NOTE : guillemets DOUBLES ("") pour un guillemet litteral en syntaxe batch
REM (pas de backslash-escape comme en shell POSIX -> \" cassait le parsing).
set "PID="
for /f "tokens=2 delims=:," %%P in ('findstr /C:"""pid""" "%LOCK%"') do (
  set "PID=%%P"
  set "PID=!PID: =!"
)

if not defined PID (
  echo [%date% %time%] lock illisible - relance par precaution.>> "%LOG%"
  goto :relancer
)

REM Le PID existe-t-il ENCORE et est-ce bien un python.exe (pas un PID recycle
REM par un autre programme depuis) ?
tasklist /FI "PID eq %PID%" /FI "IMAGENAME eq python.exe" /FO CSV 2>nul | findstr /C:"%PID%" >nul
if errorlevel 1 (
  REM Parentheses ECHAPPEES ^^^( ^^^) plus bas : une parenthese fermante non
  REM echappee DANS un bloc if^^^(...^^^) ferme prematurement le bloc pour le
  REM parseur batch -> tout ce qui suit devient une commande orpheline et casse
  REM le script. Bug reel trouve par dichotomie sur une reproduction minimale.
  echo [%date% %time%] PID %PID% mort ^(lock perime^) - relance du poller.>> "%LOG%"
  goto :relancer
)

REM Poller deja vivant : rien a faire.
popd >nul
endlocal
exit /b 0

:relancer
REM Nettoie le verrou perime (le vrai processus, s'il existe, l'aurait deja
REM libere en mourant proprement ; s'il est juste perime, ceci evite qu'
REM executer_move.py refuse de demarrer en croyant une instance deja active).
if exist "%LOCK%" del /f /q "%LOCK%" >nul 2>&1
wscript.exe "%~dp0poller_silencieux.vbs"
echo [%date% %time%] poller relance.>> "%LOG%"
popd >nul
endlocal
exit /b 0
