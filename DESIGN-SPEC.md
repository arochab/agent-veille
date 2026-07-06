# THE WIRE — Spécification design v2 : « LE CALIBRE »

*Fichier compagnon : `pwa/design-system.css` (les tokens — c'est-à-dire les variables CSS
réutilisables — et tous les composants y sont prêts). Source de vérité VISUELLE :
`da-explorations/direction-a.html` (maquette de référence, jury 13/13/11 sur 20). Public :
l'expert UX qui maintient `index.html` + `pwa/app.js`. Contrainte absolue : vanilla
HTML/CSS/JS, zéro build, zéro dépendance externe, 100% offline, dark-only.*

---

## 0. Ce qui a changé depuis v1

v1 (« terminal Bloomberg charbon/terracotta ») était techniquement propre mais générique :
warm cream / terracotta / serif — exactement le cluster visuel du design généré par IA.
v2 adopte **LE CALIBRE** : l'instrument de verdict, Bloomberg Terminal repensé par Dieter
Rams. Changements structurels :
- **Dark-only assumé**, plus de variante `prefers-color-scheme: light`. Deux raisons :
  (1) un instrument est calibré pour SA condition de lecture (téléphone, 10h, une main) ;
  (2) le public est UN builder solo déjà acculturé aux terminaux et éditeurs sombres —
  pas un grand public bancaire à rassurer par du clair institutionnel. La littérature
  fintech montre que le dark code "outil pro/technique", le clair code "confiance
  grand public" : ici seul le premier s'applique (contre-fouille business 2026-07-06).
- **Un seul accent chromatique** (`--signal`, #FFC833) au lieu de 6 couleurs ramp + terracotta
  + or + vert. Le jaune n'apparaît que dans `.tw-go` et `.tw-pipe` (grep-prouvable).
- **Angles à 0, zéro ombre, zéro dégradé.** Le relief vient des filets 1px (`--line`) et
  d'une bordure porteuse (`--edge`) quand une frontière doit franchir 3:1 UI.
- **Verdict tabulaire géant** (72px, ui-monospace) : le gain en euros, extrait du titre du
  move star, devient le plus gros pixel de l'écran.
- **Le GO** : chaque move a désormais un vrai bouton d'action (miroir visuel local du
  rituel Telegram "go N"), avec pipeline "Tes go en cours" qui s'imprime ligne par ligne.
- Toutes les classes `.tw-*` consommées par `pwa/app.js` en v1 sont **conservées** :
  seule leur habillage CSS change, sauf ajouts additifs (voir §2).

## 1. Vision

**The Wire est l'instrument de verdict d'Adam** : un écran, consulté sur mobile en 20
secondes au réveil, qui dit *quoi faire aujourd'hui pour gagner de l'argent*, avec la
confiance d'un appareil de mesure — pas d'un template. Dark-only. Chaque pixel sert la
décision. Les chiffres sont en `ui-monospace` à chasse fixe (`tabular-nums` + `slashed-zero`).
Aucune voix éditoriale décorative : pas de serif d'apparat, la headline est un microlabel
+ un titre en `system-ui` semi-gras.

## 2. Hiérarchie exacte de l'écran (de haut en bas)

1. **Masthead** : « THE WIRE » (letter-spacing 0.30em) + date, séparés par une **règle de
   ticks CSS** (`.tw-ruler`, signature n°1 — la graduation de l'instrument).
2. **Readout** (`.tw-stats`) : registre de cellules tabulaires bordées 1px — Signaux ·
   Coupés · Moves · badge DÉMO (fenêtre LCD inversée) — remplace la ligne de prose v1.
3. **Headline** — kicker « Le fil — verdict du jour » + la phrase du jour, 19px/650.
4. **Move ★ (move of the day)** — carte `.tw-move--star`, **dépliée par défaut** :
   tampon PRIORITÉ (`.tw-badge-star`, hors grille -1.4°) → **verdict** (`.tw-verdict`,
   72px) → pourquoi maintenant → **insight en fenêtre LCD** (`.tw-insight`) → do now
   (cadre `--edge`) → **bouton GO** (`.tw-go`, plein jaune) + note de scaffolding → plan
   d'exécution (registre 01/02/03) → ensuite / aussi pour.
5. **Moves 2..n** — cartes `.tw-move`, **repliées par défaut** (rang mono 02/03 + chip
   projet + meta + titre + chevron +/−). Déplié : même anatomie que la star, GO en
   version filaire (`.tw-go--ghost`).
6. **Tes go en cours** (`.tw-gos`) — pipeline local : un `.tw-pipe` par go déclenché,
   jauge 4 segments (Plan · Exécution · Preuve · Tiré), fil qui s'imprime ligne par
   ligne, ligne de preuve à l'état terminal. **Miroir visuel local (localStorage)** —
   aucune requête réseau, ne touche jamais au poller réel.
7. **Skill up** — carte pleine largeur, microlabel + texte.
8. **Footer** — mono, une ligne, discret : la salle des machines.

**Anatomie d'une carte move** (mapping exact du JSON `data/radar.demo.json`, inchangé) :
`rank` → tampon PRIORITÉ (star) ou rang mono 02/03 · `projet`+`ramp` → chip `.tw-chip`
(texte mono discret, la ramp n'est plus décorative — voir §3) · `meta` → `.tw-meta` ·
`title` → **si star et le titre contient un montant en €, ce montant est EXTRAIT en
verdict `.tw-verdict` et le reste du titre devient `.tw-move__title`** (règle de rendu :
regex ÉLARGIE au premier montant en € trouvé n'importe où dans le titre, suffixe
/mois·/an conservé (contre-audit 2026-07-06, B1 : l'ancienne regex exigeait "gagne/gain"
collé au montant, 5 titres star réels sur 6 ne matchaient pas), jamais de valeur inventée — si aucun
montant n'est trouvé, le titre s'affiche intégralement, sans verdict) · `pourquoi_maintenant`
→ `.tw-why` · `insight` → `.tw-insight` (optionnel, ≤160 car, fenêtre LCD inversée,
entre `.tw-why` et `.tw-donow`) · `do_now` → `.tw-donow` (cadre `--edge`) · **GO** :
généré par move dès que `projet` est présent — `data-go` = rang (star = "1"), `data-proj`,
`data-step1` (première étape, pour le fil pipeline) · `steps[]` → `.tw-steps` (registre
numéroté 01/02/03 ; `t`→titre, `how`→texte, `paste`→coupon copiable `.tw-paste`, bouton
COPIER pleine largeur ≥44px SOUS le texte, `done`→ligne verte « ✓ … ») + barre
`.tw-progress` (`--done`/`--total`) · `ensuite` → `.tw-ensuite` · `aussi_pour` →
`.tw-aussi` (masqué si vide).

⚠️ Champs qui n'existent plus dans le format (`intro`, `unlocks`, `miss`, `cross`,
`icone`) : jamais rendus, non lus par `app.js`.

## 3. Unicité de l'accent — le jaune n'a qu'un métier

`var(--signal)` (#FFC833, 12.57:1 vs bg-0 · 11.91:1 vs bg-1) n'apparaît que dans DEUX
familles de sélecteurs : `.tw-go` (l'action) et `.tw-pipe` (le pipeline qu'elle
déclenche — jauge et carré d'exécution). Grep-prouvable : `grep -n "var(--signal)"
pwa/design-system.css` ne doit jamais faire remonter un sélecteur en dehors de ces deux
familles.

Les 6 couleurs ramp (`blue, teal, purple, coral, amber, gray`) restent posées via
`data-ramp="…"` sur `.tw-move`, mais sont **neutralisées visuellement** : elles ne
colorent plus que le texte du chip projet (mono, discret), jamais un fond, une bordure
de carte ou une barre de progression. `gray` reste le repli si la ramp est inconnue.
Tous les couples texte/fond sont recalculés ≥ 9:1 vs bg-1 (largement au-dessus du
plancher AA), voir tableau de constantes en tête de `pwa/design-system.css` §1.

## 4. États

| État | Rendu |
|---|---|
| **Chargement** | Squelettes `.tw-skeleton--headline` + 2 `.tw-skeleton--move` (scintillement doux, angles 0). Jamais de spinner. |
| **Jour calme** (`moves` vide) | `.tw-empty` : anneaux au repos (respiration 4s, tons de gris) + « Rien d'urgent aujourd'hui. » + « Un jour calme, c'est du temps pour shipper. » |
| **Erreur de fetch** | `.tw-error` : titre `--err` (#F0A183, 9.39:1 vs bg-0), ton factuel : « Radar injoignable » + « Il se génère chaque matin à 10h. Réessaie dans un moment. » |
| **Démo vs réel** | `stats.demo: true` → cellule `.tw-badge-demo` (fenêtre LCD) dans le readout + mention footer. Réel : rien (silencieux par défaut). |
| **Go en aperçu** | `.tw-go.is-sent` : plein → filaire, texte « APERÇU ✓ » + « LANCE-LE SUR TELEGRAM : GO N » — JAMAIS « transmis » (contre-audit 2026-07-06, B2 : rien ne part d'ici, un mot qui se lit "c'est parti" serait un mensonge d'interface). Entrée ajoutée en tête de « Tes go en cours — aperçu local », persistée en localStorage (`twGosPipeline`, 8 dernières). |

## 5. Le GO et le pipeline local — règle dure

Le bouton GO (`pwa/app.js`, fonction `triggerGo`) est un **miroir visuel local** du
rituel réel "go N" sur Telegram. Il ne fait **aucune requête réseau**, n'écrit jamais
dans `data/`, ne touche jamais `data/executer_move.lock` ni le poller réel. Toute la
séquence (Reçu ✓ → Fable plan prêt ✓ → Sonnet exécute l'étape 1) est simulée en JS pur
et persistée dans `localStorage["twGosPipeline"]` pour survivre à un rafraîchissement.
La note de scaffolding sous chaque GO (« Comme répondre "go N" sur Telegram — Fable
taille le plan, Sonnet exécute. ») rend cette nature de miroir explicite pour Adam.

## 6. Règles typographiques mobile (px, mesurées au viewport 390×844)

| Élément | Famille | Taille | Graisse | Interligne |
|---|---|---|---|---|
| Verdict (le chiffre qui paie) | ui-monospace | 72px (68.4px rendus) | 700 | 0.95 |
| Headline | system-ui | 19px | 650 | 1.4 |
| Titre de move | system-ui | 16.5px | 650 | 1.38 |
| Corps (why, insight, donow) | system-ui | 15px | 400–550 | 1.5–1.55 |
| Secondaire (steps how) | system-ui | 14px | 400 | 1.5 |
| Caption (done, ensuite, footer) | system-ui / mono | 12–12.5px | 400 | 1.4 |
| Micro-labels (chips, badges) | system-ui | 11px | 400–700 | 1.35 + uppercase + 0.14em |
| Paste (coupon) | ui-monospace | 12px | 400 | 1.6 |

Prose : **max 60ch** par ligne (`--measure`). Cibles tactiles ≥ 44px partout où
l'utilisateur agit (GO, copier, étapes). Fontes système uniquement :
`ui-monospace` (Cascadia Mono/SF Mono/Menlo/Consolas), `system-ui`/Segoe UI Variable.

**Fonte nommée par le jury, non téléchargée (règle dure du projet)** : Berkeley Mono,
U.S. Graphics Company, licence commerciale (~75$),
https://usgraphics.com/products/berkeley-mono — alternative libre IBM Plex Mono (SIL OFL
1.1, https://github.com/IBM/plex). Le rendu tient déjà entièrement en `ui-monospace` :
c'est un plus optionnel pour Adam, jamais une dépendance du produit.

## 7. Logo

`assets/the-wire-logo.png` : 20px dans le masthead (réduit de 28px en v1 — l'instrument
ne met plus en avant un logo décoratif), passé en niveaux de gris via
`filter: grayscale(1) brightness(1.4)` pour rester dans le registre monochrome du
Calibre. `theme-color` unique `#0B0D10` (dark-only, pas de variante
`prefers-color-scheme`).

## 8. Micro-interactions (toutes dans le CSS/JS, sobres, auditées état par état)

- **Arrivée des cartes** : fondu + montée 6px, cascade 45ms (`style="--i:n"`).
- **Dépliage** : `.tw-fold` grid `0fr→1fr`, 240ms — pas de JS de mesure de hauteur.
- **Copie** : tap sur le bouton COPIER (sous le texte, ≥44px) → `.is-copied` (bord vert,
  « Copié ✓ »).
- **Envoi du GO** : 240ms, bascule plein → filaire.
- **Impression du fil pipeline** : 320ms par ligne, décalées (60ms/380ms/700ms), puis
  bascule Fable→Sonnet à 2200ms.
- **`prefers-reduced-motion`** : tout est coupé automatiquement ; le fil pipeline se
  rend directement à son état final (pas de lignes qui "manquent" en accessibilité).

## 9. Contraste — méthode

Tous les ratios notés en commentaire dans `pwa/design-system.css` sont **calculés**
(WCAG 2.1, luminance relative), jamais estimés — voir script de calcul utilisé pendant
l'intégration (luminance relative sRGB standard). Seuils : texte ≥ 4.5:1 (largement
dépassé partout, la plupart des couples sont ≥ 9:1), UI non-textuelle ≥ 3:1. Les filets
décoratifs (`--line`, `--tick`) sont sciemment < 3:1 : ils ne portent aucune information
non redondante avec la structure (espacement, bordures `--edge` porteuses).

## 10. Dette / non régressions vérifiées pendant la refonte

- `index.html` chargeait déjà zéro CDN / zéro font externe avant cette v2 : confirmé
  toujours vrai après (aucun `<link>` ou `<script>` distant ajouté).
- Tous les fichiers référencés par `sw.v1.js` (`ASSETS`) existent sur disque.
- `data/radar.demo.json` satisfait tous les champs lus par `pwa/app.js` (validation
  croisée manuelle) ; les champs optionnels (`insight`, `aussi_pour`) se dégradent
  silencieusement s'ils sont vides.
- `PYTHONIOENCODING=utf-8 python systeme/tests.py` reste vert (42 tests) : rien du
  moteur de scoring/jury n'a été touché par cette refonte, strictement front.
