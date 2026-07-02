# lancer_move_vscode.ps1 — ouvre VS Code sur le projet + lance Claude Code avec le move.
# Appele par executer_move.py. PowerShell gere nativement les espaces (fin du bug "Adam CHABBI Pro").
#
# Params :
#   -ProjetDir  : dossier du projet (absolu, avec espaces OK)
#   -PromptFile : fichier UTF-8 contenant l'instruction (le move)
param(
  [Parameter(Mandatory=$true)][string]$ProjetDir,
  [Parameter(Mandatory=$true)][string]$PromptFile,
  [string]$MoveMdFile = ""
)

$ErrorActionPreference = "Continue"

# 1) Depose THE-WIRE-MOVE.md a la racine du projet : Adam le voit direct dans VS Code,
#    il sait d'ou vient la session et ce qu'il y a a faire. On prefere la version
#    markdown LISIBLE (MoveMdFile) ; a defaut, le prompt brut.
$moveMd = Join-Path $ProjetDir "THE-WIRE-MOVE.md"
$entete = "# The Wire - Move a executer`r`n`r`n> **Comment lancer :** ouvre le panneau **Claude Code** (a droite dans VS Code) et ecris simplement : *suis THE-WIRE-MOVE.md*. Claude te proposera un plan et attendra ton OK avant de modifier quoi que ce soit.`r`n`r`n---`r`n`r`n"
if ($MoveMdFile -and (Test-Path -LiteralPath $MoveMdFile)) {
  $contenu = Get-Content -LiteralPath $MoveMdFile -Raw -Encoding UTF8
} else {
  $contenu = Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8
}
Set-Content -LiteralPath $moveMd -Value ($entete + $contenu) -Encoding UTF8

# 2) Depose une TACHE VS Code auto-run : a l'ouverture du dossier, VS Code lance
#    Claude Code dans son terminal INTEGRE, avec le move -> le plan sort tout seul.
#    (1 clic "Allow" la 1ere fois par projet, puis memorise.)
$vscodeDir = Join-Path $ProjetDir ".vscode"
if (-not (Test-Path -LiteralPath $vscodeDir)) { New-Item -ItemType Directory -Path $vscodeDir | Out-Null }
$tasksJson = Join-Path $vscodeDir "tasks.json"
$tache = @'
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "The Wire - Move",
      "type": "shell",
      "command": "claude",
      "args": ["--effort", "xhigh", "--permission-mode", "plan", "Lis le fichier THE-WIRE-MOVE.md a la racine de ce projet. Il decrit un move repere par mon radar de veille The Wire. Propose-moi un PLAN daction concret pour lexecuter, puis ATTENDS ma validation avant de modifier quoi que ce soit. QUAND jai valide et que tu as fini dagir : ecris a la RACINE du projet un fichier THE-WIRE-DIGEST.md qui raconte FACTUELLEMENT ce que tu as fait, avec les sections ## FAIT / ## RESTE / ## LIENS / ## NOTE, une action par puce - , separateur ' :: ' entre laction et sa preuve (chemin de fichier, ou commit sha7, ou action externe), prefixe optionnel [step N]. Ninvente rien : ne mets en FAIT que ce que tu as reellement ecrit ou commite."],
      "presentation": { "reveal": "always", "panel": "dedicated", "focus": true, "clear": true },
      "runOptions": { "runOn": "folderOpen" },
      "problemMatcher": []
    }
  ]
}
'@
Set-Content -LiteralPath $tasksJson -Value $tache -Encoding UTF8

# 3) Trouve Code.exe (le vrai binaire, pas le wrapper .cmd qui casse sur les espaces).
$codeExe = Join-Path $env:LOCALAPPDATA "Programs\Microsoft VS Code\Code.exe"
if (-not (Test-Path -LiteralPath $codeExe)) {
  $codeExe = "code"  # repli sur le PATH si install differente
}

# 4) Ouvre VS Code sur le PROJET + THE-WIRE-MOVE.md au premier plan. La tache auto-run
#    demarre Claude Code dans le terminal integre -> le plan sort tout seul. Tout dans VS Code.
& $codeExe --new-window $ProjetDir $moveMd | Out-Null
