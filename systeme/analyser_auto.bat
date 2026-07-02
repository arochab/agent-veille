@echo off
REM ============================================================================
REM  analyser_auto.bat — L'ANALYSE LLM automatique de The Wire (headless).
REM
REM  Appelle claude -p pour produire data\radar.json a partir des signaux frais.
REM  C'est la piece qui manquait : une vraie analyse LLM sans ouvrir l'app Claude.
REM  Lance par lancer_veille.bat, entre la collecte et l'envoi.
REM
REM  Prerequis : `claude` connecte (claude /login une fois). Teste par Adam OK 2026-07-01.
REM ============================================================================
setlocal EnableExtensions

set "ROOT=%~dp0.."
pushd "%ROOT%" >nul
set "LOG=data\veille.log"

REM Rien a analyser si pas de signaux frais : ce n'est PAS un echec (vrai jour calme).
if not exist "data\_pour_analyse.json" (
  echo [analyse] pas de _pour_analyse.json - rien a analyser ^(jour calme^)>> "%LOG%"
  popd >nul & endlocal & exit /b 0
)

REM LIT VRAIMENT le flag (pas juste son existence) : si la collecte dit a_analyser=false
REM (0 signal frais), on n'appelle PAS claude -> 0 token brule un jour vide.
findstr /C:"\"a_analyser\": true" "data\_a_analyser.flag" >nul 2>&1
if errorlevel 1 (
  echo [analyse] flag a_analyser=false - jour calme, pas d'appel claude>> "%LOG%"
  popd >nul & endlocal & exit /b 0
)

echo [analyse] claude -p produit le radar...>> "%LOG%"
REM claude -p lit le prompt d'analyse + les fichiers, ecrit data\radar.json.
REM SECURITE (P0 audit, ferme a 100%) : les titres Reddit/HN/GitHub sont des donnees
REM externes non maitrisees -> un titre piege ne doit JAMAIS pouvoir executer une commande
REM NI reecrire du code. Deux couches independantes :
REM  1. --settings dedie (permissions_analyse_auto.json) : Bash/WebFetch/WebSearch INTERDITS,
REM     Write/Edit verrouilles a data/** uniquement (systeme/*.py hors de portee, immunite.py
REM     compris). Fichier separe de .claude/settings.json -> tes sessions interactives
REM     normales dans ce dossier ne sont JAMAIS restreintes par ce verrou.
REM  2. Les titres eux-memes sont assainis a la source (veille.py:_assainir) avant meme
REM     d'atteindre le prompt.
REM MODELE EPINGLE : opus 4.8 explicite (la qualite du radar = le produit ; un changement
REM de defaut du CLI ne doit pas changer silencieusement le cerveau du matin).
claude -p --model claude-opus-4-8 --settings "systeme\permissions_analyse_auto.json" "Lis le fichier systeme/prompt_analyse_auto.md et suis ses instructions exactement. Lis data/_pour_analyse.json et data/atelier.json, puis ecris data/radar.json au format demande. Travaille dans le dossier courant, n'ecris que dans data/." >> "%LOG%" 2>&1

REM GARDE-FOU LIVENESS : il Y AVAIT du grain (_pour_analyse.json present) mais radar.json
REM n'a pas ete produit -> l'analyse LLM est MORTE (auth expiree, quota, plantage claude).
REM On renvoie 3 (code "analyse muette") pour que lancer_veille.bat leve une alerte :
REM un cerveau casse ne doit JAMAIS ressembler a un jour calme.
if exist "data\radar.json" (
  echo [analyse] radar.json produit OK>> "%LOG%"
  set "RC_ANALYSE=0"
) else (
  echo [analyse] ECHEC - claude -p n'a pas produit radar.json ^(analyse muette^)>> "%LOG%"
  set "RC_ANALYSE=3"
)

popd >nul
endlocal & exit /b %RC_ANALYSE%
