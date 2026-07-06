# VISION ACTIVATION - le moment GO comme point le plus puissant de The Wire

*Mission (Adam, verbatim) : "renforcer LARGEMENT la partie Activation via le Go, ca
peut etre encore plus bluffant et efficace et oriente resultats tres rapides et cash
flow, et qu'il soit a jour d'absolument tout."*

*Rappel des faits durs : le VRAI declencheur est "go N" sur Telegram
(systeme/executer_move.py). Le bouton GO du PWA est un APERCU LOCAL qui ne lance
rien (regle anti-mensonge, contre-audit 2026-07-06). Pipeline reel : Fable ecrit
PLAN-GO.md en headless (jusqu'a 8 min, PLAN_GO_TIMEOUT_S), puis VS Code s'ouvre et
Sonnet propose le plan en --permission-mode plan.*

---

## 1. Le principe : le go est un CONTRAT, pas un clic

Tout The Wire (collecte, scoring, jury, radar) n'existe que pour fabriquer 20
secondes de conviction a 10h du matin. La vision : transformer le go en un contrat
instantane en trois temps - AVANT / PENDANT / APRES - identique dans les deux
canaux, et structurellement incapable de mentir.

### AVANT le go - conviction maximale au moment de decider

Au moment ou le pouce hesite, Adam doit voir QUATRE choses, sans taper ni deplier :

- **le gain vise en euros**, extrait du titre du move (jamais invente : pas de
  montant dans le titre = pas de montant affiche - meme regle que extractVerdict
  cote PWA) ;
- **ce qui va se passer, nomme** : "Fable pose le plan, Sonnet execute sous ton
  controle" - le pipeline a deux cerveaux est un argument de vente, aujourd'hui
  invisible dans le CTA ("le plan d'execution se prepare tout seul" est correct
  mais fade) ;
- **le delai reel** : "le plan tombe en 2 a 8 min" - annonce, jamais subi ;
- **la sortie attendue** : un plan a valider, puis une preuve (commit/fichier) que
  le suivi tracera.

### PENDANT le go - zero silence, zero doute

Defaut le plus grave de l'existant : "go 1" tape -> executer_move appelle Fable en
synchrone (jusqu'a 8 minutes) AVANT le premier sendMessage. Huit minutes de silence
au moment exact de l'engagement maximal, c'est huit minutes ou Adam croit a un
plantage. Correction : un ACCUSE DE RECEPTION immediat (des la resolution du
dossier, avant Fable) qui verrouille le move, recopie le gain vise, et annonce le
delai. Puis le message final existant (plan pose / repli), inchange dans son
honnetete.

### APRES le go - le premier euro, pas juste un plan

- Le message de confirmation re-ancre le cash : gain + do_now (le premier euro) +
  les commandes de cloture ("fait N", "paye N <montant>") - aujourd'hui il est
  purement operationnel, l'instant de conviction retombe a plat.
- Le PLAN-GO.md de Fable ouvre sur un **PREMIER GESTE de moins de 15 minutes**
  (l'action a faire des validation, texte pret-a-coller si applicable) et declare
  une **PREUVE ATTENDUE** par etape (quel fichier/commit prouvera le done, format
  " :: " aligne sur THE-WIRE-DIGEST.md) - la boucle action->preuve->cash devient
  visible AVANT d'agir, pas seulement apres coup via "statut".
- Le suivi et le digest mesurent le time-to-cash reel (jours go->fait, go->paye),
  a partir de dates prouvees uniquement.

## 2. Le PWA : de vitrine parallele a miroir VRAI

Rupture actuelle : deux univers sous le meme nom de section. Les vrais go Telegram
sont invisibles dans le PWA ; les clics PWA sont invisibles du vrai suivi. Le PWA
ne peut montrer AUCUN resultat cash reel.

Correction honnete et purement en lecture :

- **Etat reel** : le PWA lit `data/go_suivi.json` en same-origin (exactement comme
  il lit deja `data/radar.json` - zero requete externe, zero contact avec le
  poller). Section "Tes go - etat reel (lu du suivi)" : statut, preuve citee,
  montant paye, date relative - champs RECOPIES du JSON, aucun calcul d'etat cote
  front. Fichier absent (GitHub Pages, donnees privees) : section masquee, rien
  d'invente.
- **Apercu au conditionnel** : la simulation locale reste, mais parle au
  conditionnel ("Fable poserait le plan - en vrai : 2 a 8 min", "Sonnet executerait
  l'etape 1 : ..."), plus jamais a l'indicatif accompli. L'ecart de rythme (2.2 s
  simules vs 8 min reelles) est nomme dans l'apercu lui-meme. Etat terminal :
  toujours "APERCU", jamais un mot qui se lit "c'est parti".
- **Le seul pont vers le reel est un presse-papiers** : un bouton "Copier go N"
  sous chaque GO. Adam colle dans Telegram - deux gestes, zero mensonge, zero
  requete.
- Les deux listes (reel / apercu) ne sont JAMAIS fusionnees ni confondues.

## 3. "A jour d'absolument tout" - une seule langue partout

- Le CTA Telegram nomme Fable et Sonnet comme le fait deja le bouton PWA
  ("Fable planifie / Sonnet execute").
- Les delais affiches derivent de PLAN_GO_TIMEOUT_S, pas d'un chiffre en dur.
- Les noms produits (config_projets/NOMS_AFFICHAGE), le lexique emoji fixe, les
  ramps projet et le jaune --signal (reserve GO + pipeline) restent la meme voix
  dans le radar, le suivi, le digest et le PWA.
- Tiret simple "-" partout dans le contenu affiche (regle anti-IA d'Adam,
  permanente) ; WCAG >= 4.5:1 calcule ; prefers-reduced-motion respecte.

## 4. Regle anti-mensonge (inviolable, verifiable)

Rien, nulle part, ne peut faire croire a un go reel qui n'a pas eu lieu :

1. Le bouton GO du PWA ne fait AUCUNE requete (grep-prouvable : aucun fetch ajoute
   hors des sources same-origin declarees dans pwa/config.js).
2. L'etat reel affiche par le PWA vient exclusivement de data/go_suivi.json, en
   lecture seule, recopie sans interpretation ; absent = masque.
3. Tout montant affiche est extrait d'un champ existant (titre du move, montant
   paye confirme) - jamais calcule, jamais invente.
4. "paye" ne nait que d'une confirmation d'Adam ou d'un event feedback (hierarchie
   de suivi_go inchangee) ; la PREUVE ATTENDUE de PLAN-GO.md est toujours attribuee
   ("annonce par Fable"), jamais promue en fait systeme.
5. Les messages Telegram gardent leurs deux branches distinctes (plan Fable pose /
   repli direct) et disent mot pour mot que rien n'est ecrit sans OK d'Adam.

## 5. Decoupage en 3 leviers a fichiers DISJOINTS

| Levier | Perimetre fichiers | Coeur |
|---|---|---|
| 1. Telegram - l'instant du go | systeme/envoyer_telegram.py, systeme/executer_move.py | CTA nomme + gain, accuse de reception immediat, confirmation re-ancree cash |
| 2. PWA - miroir vrai | pwa/app.js, pwa/config.js, pwa/design-system.css, index.html, sw.v1.js, DESIGN-SPEC.md | Etat reel lu de go_suivi.json, apercu au conditionnel, bouton "Copier go N" |
| 3. Plan post-go + boucle preuve | systeme/prompt_plan_go.md, systeme/suivi_go.py, systeme/digest_roi.py, systeme/tests_plan_go.py | PREMIER GESTE 15 min + PREUVE ATTENDUE dans PLAN-GO, preuve attendue attribuee dans le suivi, time-to-cash dans le digest |

Sentinelles immunite.py touchees (a lister pour rescellement en fin de vague) :
envoyer_telegram.py, executer_move.py (levier 1) ; suivi_go.py, digest_roi.py
(levier 3). Filet permanent : `PYTHONIOENCODING=utf-8 python systeme/tests.py`
vert ; data/ = production (tout fichier touche par un test : .bak, restauration
prouvee, .bak supprime) ; radar.demo.json en lecture seule.
