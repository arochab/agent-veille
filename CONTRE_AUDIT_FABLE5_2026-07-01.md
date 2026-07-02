# CONTRE-AUDIT FABLE 5 — vérification de TRAVAUX_2026-07-01.md

Auditeur : Fable 5, session indépendante. Méthode : chaque affirmation du document
confrontée au code réel (lecture directe des fichiers aux lignes citées), tests
ré-exécutés par l'auditeur (jamais recopiés du document), état git relu, diffs des
fichiers non revendiqués inspectés. Aucune PII ni secret ci-dessous.

---

## 1. Verdict global sur le document

**Le document est substantiellement honnête et précis.** Sur ~30 affirmations
vérifiables (citations fichier:ligne, état git, résultats de tests, points déclarés
non traités), je n'ai trouvé **aucune affirmation fausse sur le fond**, 1 imprécision
technique de mécanisme, 2 dérives mineures de numéros de ligne, et **1 omission
substantielle** que le document aurait dû déclarer (voir § 5, écart E4). Les
auto-déclarations défavorables (rien de commité, fichier de debug oublié, bug du
faux ~1€ auto-introduit, unification partielle) sont toutes **exactes** — le
document ne s'est pas donné le beau rôle.

---

## 2. Vérifications reproduites par l'auditeur (résultats RÉELS de ce contre-audit)

```
$ python systeme/tests.py
Ran 30 tests in 0.197s
OK
FILET VERT - le systeme est sain, l'auto-amelioration peut tourner.
```
Conforme au document (30 tests, OK ; la durée 0.137s vs 0.197s est du bruit de mesure).

```
$ python -c "... immunite.verifier()"
{'ok': True, 'halt': False, 'alteres': [], 'manquants': [], 'raison': ''}
```
Identique au document. Le hash de `feedback.py` dans `systeme/immunite.py:37` est
exactement celui cité (`6f1ef6...e31e6`). Le dict `ATTENDUS` contient bien les 6
organes déclarés, et PAS les fichiers de cette session — conforme à la faiblesse
auto-déclarée.

```
$ digest_roi.calculer_digest() / formater_digest()   [exécuté par l'auditeur]
nb_lances: 2 | nb_paye: 0 | nb_en_cours: 2 | potentiel: 0
LEN: 489 | <b> 4/4 | <i> 1/1 | 'Potentiel' absent du message
```
**Reproduction exacte**, y compris la longueur de 489 caractères citée par le
document — le chiffre n'était pas inventé. Le bug du faux "~1€" est confirmé
corrigé sur les données réelles (potentiel = 0, section absente).

```
$ Get-ScheduledTask TheWire-DigestROI-Vendredi18h
State: Ready
```
La tâche planifiée du digest existe et est active — conforme.

État git : `git log` montre exactement 3 commits (`366d87c`, `47fc9f4`, puis
`1a2db8f` = le document lui-même). **La déclaration « aucun commit pour le code
métier » est vraie.** Le `git status --short` réel correspond ligne pour ligne au
tableau du § 6 du document. Le fichier parasite `claude` est absent de la racine ;
zéro fichier `.tmp*` orphelin dans `data/`.

---

## 3. Citations fichier:ligne — vérifiées une par une

| Affirmation du document | Réalité vérifiée | Verdict |
|---|---|---|
| `veille.py:37` TITRE_MAX=220, `_assainir` 37-49 | TITRE_MAX ligne 37, `_assainir` lignes 40-49 | ✅ (mécanisme : voir écart E1) |
| `permissions_analyse_auto.json` : allow Read/Write(./data/**)/Edit(./data/**), deny Bash/WebFetch/WebSearch/Write(systeme,..) | Contenu exact, au caractère près | ✅ |
| `analyser_auto.bat:44` : `--model claude-opus-4-8 --settings ...` | Ligne 44 exacte ; garde `findstr a_analyser` lignes 25-28 ; code 3 « analyse muette » lignes 50-56 | ✅ |
| `lancer_veille.bat:83-97` : RC_ENVOI ligne 84, garde ligne 89, archive 91, alerte 95 | Lignes 84 / 89 / 91 / 95, exactes toutes les quatre | ✅ |
| `collecte_signaux.py:69` CANAUX_VITAUX_FIXES, `:72` `_canaux_vitaux()`, `:260` message cookie | Lignes 69, 72, 260 exactes ; site d'appel (non cité par prudence) trouvé ligne 354 | ✅ |
| Point ouvert déclaré : « pas re-grep l'ancien nom CANAUX_VITAUX » | Grep exhaustif fait par l'auditeur : **zéro usage résiduel** du nom nu dans tout le code — le point ouvert se referme proprement | ✅ résolu |
| `atomic_io.py` : tmp+PID, `Path.replace()`, False sans exception, nettoyage du tmp | Conforme lignes 27-50 | ✅ |
| `feedback.py:107-116` : journal AVANT registre | `EVENTS.open("a")` ligne 113, `vu.add` 115, `write_json_atomic(VU,...)` 116 — ordre exact | ✅ |
| `suivi_go.py` : 3 occurrences `write_json_atomic(OUT, snap)` | Lignes 1307, 1420, 1438 — exactement 3 | ✅ |
| `executer_move.py:121-131` save_json atomique | Réel : import config_projets 121-126, `save_json` **129-140** | ✅ fond / ⚠ lignes (E2) |
| `executer_move.py` resoudre_dossier ~326-344, config-first + repli + verrou intact | Fonction ligne 326 ; config-first 342-345 ; verrou (c) intact lignes 360-362 | ✅ |
| `suivi_go.py` `_nom_affichage` ~1518-1531 | Réel : **1525-1539** (config-first + repli NOMS_AFFICHAGE conformes) | ✅ fond / ⚠ lignes (E3) |
| `digest_roi.py:109` `_RE_MARQUEUR_EURO`, `:112-131` `_extraire_montant_estime` | Lignes 109 et 112-131 exactes ; la permissive `_extraire_montant_euros` bien conservée pour `montant` (lignes 95-105) | ✅ |
| `envoyer_telegram.py` : format/envoyer_envoi_echoue, envoyer_digest_roi, modes CLI | Présents lignes 286, 307, 334 ; les 4 flags parsés 349-352 ; `_refendre_si_trop_long` ligne 49 | ✅ |
| `config_projets.py` : cache, contrat {} / None sans exception, 5 fonctions | Conforme intégralement | ✅ |
| `data/projets.json` : 10 projets | 10 exactement (compté par l'auditeur) | ✅ |
| Pare-feu ajouté à `prompt_analyse_auto.md` seulement, texte tiers ligne ~31 intact | Pare-feu lignes 7-16 de ce fichier uniquement ; texte TIER1/2/3 statique ligne 31, non branché | ✅ |
| `scoring.py` non touché ; divergence `pacto-club` vs slug `mixhub` réelle | Contrat « AUCUN I/O » ligne 14 ; `"pacto-club"` dans TIER3 ligne 45 alors que projets.json utilise le slug `mixhub` — la raison invoquée pour ne pas unifier est réelle, pas une excuse | ✅ |
| Diffs `M` non revendiqués (radar.demo.json, PROMPT_RADAR.md, scan_atelier.py) | Inspectés : contenu = avancement projet / exploitation du score / SKIP list — travail antérieur, aucun rapport avec les 5 actions du document | ✅ cohérent |
| P2 déclarés non traités | Vérifiés toujours présents : pas de `import urllib.error` dans envoyer_telegram.py (lignes 14-15 : request/parse seulement) ; `_pid_vivant` ligne 789 inchangé ; `lancer_move.bat` toujours là | ✅ exact |

---

## 4. Sécurité (relecture indépendante, pas sur parole)

- **P0 : réellement fermé.** Deux couches indépendantes vérifiées dans le code :
  le verrou `--settings` est une permission DURE (deny Bash/WebFetch/WebSearch,
  Write/Edit hors data/ refusés), pas une consigne de prompt ; le sanitizer coupe
  les vecteurs structurels. Le document ne sur-vend pas : il déclare lui-même que
  la couche sémantique reste molle (un texte manipulateur reste lisible par le
  modèle, seul le pare-feu du prompt s'y oppose). Évaluation partagée.
- **Verrou de chemin d'`executer_move.py`** : la borne dure à l'atelier
  (`p_res.parents` + comparaison résolue, lignes 360-362) est intacte ; le
  branchement config_projets n'y ouvre aucun contournement (il ne fait que
  proposer un nom AVANT le verrou, jamais après).
- **Résidus non couverts (confirmés, déjà déclarés)** : `immunite.py` ne se
  protège pas lui-même ; les organes d'exécution/livraison (`executer_move.py`,
  `envoyer_telegram.py`, `suivi_go.py`, `collecte_signaux.py`, `digest_roi.py`,
  `atomic_io.py`, `config_projets.py`) ne sont pas hashés.
- **Nouveau, relevé par l'auditeur** : `atomic_io.write_json_atomic` n'appelle pas
  `fsync` avant le `replace()`. Contre un crash de PROCESS (la menace annoncée),
  c'est correct. Contre une coupure de COURANT, l'OS peut réordonner : le rename
  peut survivre sans les données. Risque faible sur un poste de travail, mais la
  garantie réelle est « anti-crash-process », pas « anti-coupure-secteur » — le
  docstring dit « crash/coupure », c'est légèrement optimiste.

---

## 5. Écarts entre le document et la réalité

**E1 — Imprécision de mécanisme (§ 1 du document) : la description du sanitizer
est techniquement inexacte.** Le document affirme que `_assainir` retire « les
caractères de contrôle (`\x00-\x1f`, `\x7f`, y compris `\n`/`\r`) ». Le regex réel
(`veille.py:36`) est `[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]` : il **exclut délibérément**
`\t` (x09), `\n` (x0a) et `\r` (x0d). Ces trois-là sont neutralisés par l'étape
suivante (`re.sub(r"\s+", " ")`, ligne 46), pas par le retrait des caractères de
contrôle. **Le comportement net revendiqué est vrai** (aucun saut de ligne ne
survit — vérifié en lisant les deux étapes), mais l'attribution du mécanisme est
fausse. Gravité : cosmétique, aucun impact sécurité.

**E2 — Citation de lignes dérivée (§ 4) :** `executer_move.py:121-131` pour
`save_json` ; en réalité la fonction est aux lignes **129-140** (121-126 = le bloc
d'import config_projets). Le contenu décrit existe intégralement. Gravité : mineure.

**E3 — Citation de lignes dérivée (§ 5a) :** `suivi_go.py` `_nom_affichage`
annoncée « ~1518-1531 » ; réel **1525-1539**. Le tilde annonçait l'approximation ;
dérive de ~7 lignes. Contenu conforme. Gravité : mineure.

**E4 — OMISSION SUBSTANTIELLE (non déclarée par le document) :
`data/projets.json`, la « source unique de vérité » créée en § 5a, est
GITIGNORÉE.** `.gitignore` contient `data/*` (avec pour seule exception
`radar.demo.json`). Conséquences que le document aurait dû déclarer :
- ce fichier ne sera **jamais versionné ni committé** — pas d'historique, pas de
  récupération possible via git en cas de suppression/corruption ;
- il n'est **pas non plus** protégé par l'immunité ;
- il est donc le seul artefact de configuration du système sans AUCUN filet,
  alors même qu'il a vocation à devenir la référence. Les replis figés dans le
  code limitent la casse (le système survit à sa perte), mais toute donnée
  saisie UNIQUEMENT dans projets.json (ex. futurs projets ajoutés là et pas
  dans les dicts figés) serait perdue sans trace.
  Le choix de gitignorer `data/` est par ailleurs légitime (données stratégiques
  personnelles) — le problème n'est pas l'ignore, c'est l'absence de mention et
  de stratégie de sauvegarde pour ce fichier précis.

**E5 — Invérifiable par nature (à connaître, pas un reproche) :** toutes les
narrations de tests « à état restauré » (token cassé puis restauré, `rdt.exe`
renommé puis remis, 16 alias testés un par un, events de feedback nettoyés) ne
laissent par construction **aucune trace vérifiable**. Tout ce qui était
re-exécutable a été re-exécuté par l'auditeur et a reproduit exactement les
valeurs du document (30 tests, immunité, digest 489 caractères, balises 4/4 et
1/1, potentiel absent, tâche planifiée Ready) — ce qui rend le reste crédible,
mais crédible n'est pas prouvé.

**E6 — Nuance de périmètre (§ 6/§ 7) :** le document attribue `tests.py` (dont
`TestReste` et `TestApparier`) à « une session antérieure » ; le fichier étant
non suivi par git, aucune baseline ne permet de départager les frontières de
session. Invérifiable, sans enjeu (le document ne s'attribue rien, il refuse
au contraire du crédit).

Aucun autre écart trouvé. En particulier : la déclaration des diffs `M` non
revendiqués est **exacte** (leur contenu réel — `avancement_recent`,
exploitation du score, SKIP list — appartient à une phase antérieure) ; le
point ouvert du § 3 (grep CANAUX_VITAUX) se referme en faveur du document.

---

## 6. Notation — 8 dimensions /20

Référence : l'audit précédent (avant remédiation) donnait ~11,5/20 avec un P0 ouvert.

| Dimension | Note | Justification (faits vérifiés par l'auditeur) |
|---|---|---|
| **Fiabilité** | **14/20** | Écritures atomiques réelles sur 4 modules (vérifiées ligne à ligne), ordre journal-avant-registre corrigé, garde RC_ENVOI empêchant la perte silencieuse du radar, code 3 « analyse muette », replis systématiques. 30 tests verts reproduits. Retenu : TOUT le code métier est non commité (une fausse manœuvre git efface la session entière) ; `projets.json` sans filet (E4) ; digest non testé à l'échelle. |
| **Sécurité** | **13/20** | P0 réellement fermé par une permission dure + sanitizer (vérifiés dans le code, pas sur parole) ; verrou de chemin intact ; modèle épinglé. Retenu : immunité ne couvre ni elle-même ni les organes d'exécution/livraison ; défense sémantique molle (assumée) ; `write_json_atomic` sans fsync (garantie anti-crash, pas anti-coupure). |
| **Architecture** | **13/20** | Séparation nette déterministe/LLM ; module atomique commun ; contrat de repli propre et UNIFORME dans les 3 branchements config ; contrat de pureté de scoring.py respecté. Retenu : unification 3/5 seulement, divergence de nommage `pacto-club`/`mixhub` toujours pendante, texte tiers du prompt pouvant diverger silencieusement. |
| **Économie de tokens** | **16/20** | Le meilleur poste : garde `findstr` = zéro appel claude un jour vide (vérifié lignes 25-28) ; scoring, clarifier, digest, suivi = 100% déterministes ; un seul appel LLM par jour, modèle et périmètre épinglés. Retenu : pas de plafond/télémétrie de consommation sur l'appel du matin. |
| **Scalabilité** | **10/20** | Collecte séquentielle mono-machine ; un seul canal de sortie (Telegram, alerte d'échec incluse mais sans canal de secours — assumé) ; digest jamais testé au-delà de 2 go ; `_refendre_si_trop_long` existe mais la composition à fort volume n'est pas éprouvée. Rien de bloquant à l'échelle actuelle (1 utilisateur), mais rien de prouvé au-delà. |
| **Cash-machine** | **11/20** | La boucle signal→go→preuve→payé existe de bout en bout et le digest ROI la rend visible chaque vendredi (tâche vérifiée Ready) ; « payé » impossible à halluciner (hiérarchie de preuves) ; potentiel estimé strict (le faux ~1€ est mort — reproduit à 0 sur données réelles). Retenu : 0€ confirmé à ce jour, 2 go en cours seulement — la machine est câblée, pas encore alimentée. |
| **Future-proof** | **11/20** | Modèle épinglé, settings dédiés hors du chemin des sessions interactives, stdlib-only, replis partout. Retenu : le point le plus anti-future-proof du projet est l'état git lui-même (tout en `??`/`M`, un seul commit = le rapport) ; re-signature manuelle des hash = friction qui incite à ne pas protéger les nouveaux organes ; config de référence non versionnée (E4). |
| **Vision 2035** | **12/20** | Le pattern est le bon : agent contraint par des permissions dures, données externes traitées en données, preuves avant déclarations, auto-réparation et jury avant publication, digest de ROI qui ferme la boucle. C'est structurellement une machine agentique saine. Retenu : mémoire/apprentissage encore minces (poids appris mais peu exploités), pas de second canal, pas d'abstraction de livraison. |

**Moyenne : 12,5/20** (contre ~11,5 avant la session). La progression est réelle et
concentrée là où elle devait l'être (sécurité, fiabilité) ; les points bas restants
(scalabilité, cash) sont des chantiers déclarés, pas des angles morts.

---

## 7. Les 3 actions que ce contre-audit impose (par ordre)

1. **COMMITTER le travail de la session, maintenant.** C'est le risque n°1 du
   projet à cette heure : ~10 fichiers créés/modifiés, testés, fonctionnels — et
   récupérables par personne s'ils disparaissent. Le document lui-même le déclare ;
   le contre-audit le confirme et le promeut de « déclaré » à « urgent ».
2. **Donner un filet à `data/projets.json`** (E4) : soit une exception `.gitignore`
   ciblée (`!data/projets.json` — le fichier ne contient ni secret ni signal, je
   l'ai lu : noms de projets, tiers, alias, requêtes), soit le déplacer sous
   `systeme/` versionné, soit a minima l'ajouter aux organes de l'immunité.
3. **Corriger les 2 imprécisions du document** (E1 mécanisme du sanitizer, E2/E3
   numéros de ligne) si ce document doit servir de référence — ou les considérer
   soldées par le présent rapport.

---

*Contre-audit exécuté indépendamment : tests relancés, immunité relancée, digest
recalculé, tâche planifiée relue, chaque citation ouverte dans le fichier réel.
Rien dans ce rapport n'est recopié du document audité sans avoir été reproduit.*
