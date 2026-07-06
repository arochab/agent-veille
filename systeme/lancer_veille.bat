@echo off
REM ============================================================================
REM  lancer_veille.bat - Auto-pilote de "The Wire" (tache #3a)
REM
REM  Chaine complete, lancable par le Planificateur de taches Windows :
REM    1. python systeme\veille.py        -> collecte + marqueur _a_analyser.flag
REM    2. (relais Claude pour l'analyse : le marqueur dit s'il y a du grain)
REM    3. si PANNE detectee               -> push alerte Telegram --incident
REM    4. si data\radar.json existe        -> push du radar du jour
REM
REM  Tout est loggue dans data\veille.log (date + resultat de chaque etape).
REM  Aucune fenetre bloquante : pas de PAUSE, sortie immediate a la fin.
REM
REM  Codes veille.py : 0 = OK (ou jour calme), 1 = echec dur, 2 = PANNE canal.
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion

REM --- Racine du projet = dossier parent de ce .bat (\systeme\..) ---
set "ROOT=%~dp0.."
pushd "%ROOT%" >nul

set "LOG=data\veille.log"
if not exist "data" mkdir "data"

REM --- Trouve un Python utilisable (py launcher sinon python) ---
set "PYEXE=python"
where py >nul 2>&1 && set "PYEXE=py"

REM --- Horodatage ISO-ish, independant de la locale (via Python) ---
for /f "delims=" %%T in ('%PYEXE% -c "import datetime;print(datetime.datetime.now().isoformat(timespec=\"seconds\"))"') do set "NOW=%%T"

echo.>> "%LOG%"
echo ===== RUN %NOW% =====>> "%LOG%"

REM --- 1. Collecte (veille.py) ---
echo [%NOW%] 1/3 collecte (veille.py)...>> "%LOG%"
%PYEXE% systeme\veille.py >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo [%NOW%] veille.py code retour = !RC!>> "%LOG%"

REM --- 2. ANALYSE LLM AUTOMATIQUE (claude -p, headless) -> data\radar.json ---
REM     La vraie analyse : un Claude lit les signaux + le prompt et ecrit le radar,
REM     SANS ouvrir l'app. C'est ce qui rend The Wire 100% autonome chaque matin.
set "RC_ANALYSE=0"
if exist "data\_a_analyser.flag" (
  echo [%NOW%] analyse LLM auto ^(claude -p^)...>> "%LOG%"
  call "%~dp0analyser_auto.bat"
  set "RC_ANALYSE=!ERRORLEVEL!"
  echo [%NOW%] analyse terminee code = !RC_ANALYSE!>> "%LOG%"
)

REM --- 3. ALERTE PANNE (prioritaire, distincte du brief) ---
if "!RC!"=="2" (
  echo [%NOW%] PANNE detectee - envoi alerte Telegram --incident>> "%LOG%"
  %PYEXE% systeme\envoyer_telegram.py --incident >> "%LOG%" 2>&1
  echo [%NOW%] alerte panne code retour = !ERRORLEVEL!>> "%LOG%"
)

REM --- 3bis. ALERTE ANALYSE MUETTE : il y avait du grain mais claude -p n'a rien produit.
REM     Un cerveau casse (auth expiree, quota) ne doit JAMAIS ressembler a un jour calme.
if "!RC_ANALYSE!"=="3" (
  echo [%NOW%] ANALYSE MUETTE detectee - envoi alerte Telegram --analyse-morte>> "%LOG%"
  %PYEXE% systeme\envoyer_telegram.py --analyse-morte >> "%LOG%" 2>&1
  echo [%NOW%] alerte analyse muette code retour = !ERRORLEVEL!>> "%LOG%"
)

REM --- 4. Push du radar du jour SI l'analyse a produit data\radar.json ---
REM     GARDE-FOU FINAL : le jury de clarte doit dire GO, sinon on n'envoie PAS.
if exist "data\radar.json" (
  echo [%NOW%] jury de clarte sur data\radar.json...>> "%LOG%"
  %PYEXE% systeme\jury_clarte.py data\radar.json >> "%LOG%" 2>&1
  set "JURY=!ERRORLEVEL!"
  REM Si NO-GO : AUTO-REPARATION (raccourcit les champs trop longs sans couper un mot),
  REM puis on re-juge. La prod ne bloque jamais pour une simple longueur.
  if not "!JURY!"=="0" (
    echo [%NOW%] jury NO-GO - tentative d'auto-reparation...>> "%LOG%"
    %PYEXE% systeme\auto_reparer.py data\radar.json >> "%LOG%" 2>&1
    %PYEXE% systeme\jury_clarte.py data\radar.json >> "%LOG%" 2>&1
    set "JURY=!ERRORLEVEL!"
  )
  if "!JURY!"=="0" (
    echo [%NOW%] jury GO - envoi du radar Telegram>> "%LOG%"
    %PYEXE% systeme\envoyer_telegram.py >> "%LOG%" 2>&1
    set "RC_ENVOI=!ERRORLEVEL!"
    echo [%NOW%] envoi radar code retour = !RC_ENVOI!>> "%LOG%"
    REM GARDE-FOU (audit Fable P1-2) : n'ARCHIVER (donc ne JAMAIS supprimer radar.json)
    REM QUE si l'envoi a reussi. Sinon le radar reste sur disque pour un prochain essai,
    REM et une alerte part -> un echec d'envoi ne doit JAMAIS ressembler a un jour calme.
    if "!RC_ENVOI!"=="0" (
      REM HUB Second Cerveau : emet le radar vers le hub AVANT l'archivage (radar.json
      REM existe encore). Optionnel et non bloquant : si le module ou le repo hub
      REM manquent, hub_radar ne fait rien et le run continue normalement.
      %PYEXE% systeme\hub_radar.py >> "%LOG%" 2>&1
      echo [%NOW%] radar emis vers le hub ^(hub_radar^)>> "%LOG%"
      REM Archive le radar date + libere radar.json (anti re-spam, anti double-comptage).
      %PYEXE% systeme\feedback.py --archive >> "%LOG%" 2>&1
      echo [%NOW%] radar archive ^(feedback.py --archive^)>> "%LOG%"
    ) else (
      echo [%NOW%] ENVOI ECHOUE - radar.json CONSERVE ^(pas archive^), alerte envoyee>> "%LOG%"
      %PYEXE% systeme\envoyer_telegram.py --envoi-echoue >> "%LOG%" 2>&1
      echo [%NOW%] alerte envoi-echoue code retour = !ERRORLEVEL!>> "%LOG%"
    )
  ) else (
    REM GARDE-FOU (audit Fable, vague 2B) : un NO-GO persistant etait jusqu'ici
    REM une panne 100% silencieuse (rien que le log) -> un defaut de FOND ne doit
    REM JAMAIS ressembler a un jour calme, meme punition que les autres pannes.
    echo [%NOW%] jury NO-GO persistant ^(defaut de FOND^) - radar PAS envoye, alerte envoyee.>> "%LOG%"
    %PYEXE% systeme\envoyer_telegram.py --jury-nogo >> "%LOG%" 2>&1
    echo [%NOW%] alerte jury-nogo code retour = !ERRORLEVEL!>> "%LOG%"
  )
) else (
  echo [%NOW%] pas de data\radar.json - rien a pousser ^(analyse pas encore faite^).>> "%LOG%"
)

echo [%NOW%] ===== FIN RUN =====>> "%LOG%"

popd >nul
endlocal
REM Sortie immediate, jamais de PAUSE : aucune fenetre ne reste ouverte.
exit /b 0
