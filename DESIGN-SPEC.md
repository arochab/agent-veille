# THE WIRE — Spécification design v1

*Fichier compagnon : `pwa/design-system.css` (les tokens — c'est-à-dire les variables CSS
réutilisables — et tous les composants y sont prêts). Public : l'expert UX qui refond
`index.html` + `pwa/app.js`. Contrainte absolue : vanilla HTML/CSS/JS, zéro build, zéro
dépendance externe, 100% offline.*

---

## 1. Vision

**The Wire est le terminal Bloomberg d'Adam** : un écran, consulté sur mobile en 20 secondes
au réveil, qui dit *quoi faire aujourd'hui pour gagner de l'argent*. Le ton visuel :
**sombre, dense, premium, zéro gadget**. Sombre par défaut (lecture du matin, cohérence avec
le logo charbon/terracotta), variante claire automatique si le téléphone est en mode clair.
Chaque pixel sert la décision ; rien ne décore. Les chiffres sont en monospace à chasse fixe
(`tabular-nums` : tous les chiffres ont la même largeur, comme sur un terminal financier).
La seule voix éditoriale : la **headline en serif**, comme une une de journal.

## 2. Hiérarchie exacte de l'écran (de haut en bas)

1. **Header** : logo (28px) + « THE WIRE » + date du radar (monospace, à droite).
2. **Headline** — la phrase du jour, serif 22px. C'est le titre de la une : rien au-dessus d'elle ne doit crier.
3. **Move ★ (move of the day)** — carte `.tw-move--star`, **dépliée par défaut**, lavis chaud + halo terracotta + badge or `.tw-badge-star`. C'est la star : une seule carte a ce traitement.
4. **Moves 2..n** — cartes `.tw-move`, **repliées par défaut** (visible : chip projet + meta + titre + chevron). Tap sur le head → `.is-open` déplie (`.tw-fold`, transition douce).
5. **Skill up** — carte `.tw-skill` (bord vert), l'apprentissage de la semaine.
6. **Stats + footer** — `x fresh · y coupés` en monospace, badge démo éventuel, mention de génération. Discret : c'est la salle des machines, pas le spectacle.

**Anatomie d'une carte move** (mapping exact du JSON `data/radar.demo.json`) :
`rank` → badge ★ ou numéro dans le rail · `projet`+`ramp` → chip `.tw-chip[data-ramp]` ·
`meta` → `.tw-meta` · `title` → `.tw-move__title` · `pourquoi_maintenant` → `.tw-why` ·
`insight` → `.tw-insight` (optionnel, ≤160 car — la lecture STRATÉGIQUE : ce que le fait
implique, filet accent italique, entre `.tw-why` et `.tw-donow` ; voir SPEC-INSIGHT-2B.md) ·
`do_now` → encart accentué `.tw-donow` (label « do now », bord terracotta — LA première action) ·
`steps[]` → `.tw-steps` (rail numéroté ; `t`→titre, `how`→texte, `paste`→bloc copiable
`.tw-paste`, `done`→ligne verte « ✓ … ») + barre `.tw-progress` (`--done`/`--total`) ·
`ensuite` → `.tw-ensuite` · `aussi_pour` → `.tw-aussi` (masquer si vide).
⚠️ L'`app.js` actuel rend des champs qui n'existent plus dans le format (`intro`, `unlocks`,
`miss`, `cross`, `icone`) : à supprimer lors de la refonte.

## 3. Les 6 couleurs ramp — le code visuel des projets

Chaque projet a sa couleur (`blue, teal, purple, coral, amber, gray`) : elle est **l'identité
du projet**, jamais décorative. Poser `data-ramp="…"` sur la carte suffit — le CSS décline
automatiquement : bord gauche de carte (`--ramp-solid`), chip (`--ramp-bg`+`--ramp-text`),
numéros de steps, barre de progression. `gray` est aussi le repli si la ramp est inconnue.
Tous les couples texte/fond sont ≥ 4.5:1 (WCAG AA, ratios calculés en commentaire dans le CSS).
La terracotta (`--accent`) reste réservée à la marque : do-now, copie, focus, anneaux du radar.

## 4. États

| État | Rendu |
|---|---|
| **Chargement** | Squelettes `.tw-skeleton--headline` + 2 `.tw-skeleton--move` (scintillement doux). Jamais de spinner. |
| **Jour calme** (`moves` vide) | `.tw-empty` : anneaux du radar au repos (respiration 4s) + « Rien d'urgent aujourd'hui. » + « Un jour calme, c'est du temps pour shipper. » Élégant, jamais un écran d'échec. |
| **Erreur de fetch** (aucune source ne répond) | `.tw-error` : titre coloré `--err`, ton factuel : « Radar injoignable » + « Il se génère chaque matin à 10h. Réessaie dans un moment. » |
| **Démo vs réel** | `stats.demo: true` → badge `.tw-badge-demo` « données démo » près des stats + mention footer. Radar réel : rien (le réel est le défaut silencieux). |

## 5. Règles typographiques mobile (px, base 560px max)

| Élément | Famille | Taille | Graisse | Interligne |
|---|---|---|---|---|
| Headline | serif système | 22px | 500 | 1.35 |
| Titre de move | system-ui | 17px | 650 | 1.3 |
| Corps | system-ui | 15px | 400 | 1.55 |
| Secondaire (why, how, skill) | system-ui | 13px | 400 | 1.5 |
| Caption (done, ensuite, date) | system-ui / mono | 12px | 400 | 1.4 |
| Micro-labels (chips, badges) | system-ui | 11px | 650–700 | 1.35 + uppercase + 0.06em |
| Paste | ui-monospace | 12px | 400 | 1.55 |

Prose : **max 65ch** par ligne (`--measure`). Cibles tactiles ≥ 44px (le `.tw-paste` l'impose).
Aucune font externe : `system-ui`, `ui-serif`/Georgia, `ui-monospace` uniquement.

## 6. Logo

`assets/the-wire-logo.png` (512px, anneaux terracotta sur charbon) : 28px arrondi dans le
header, jamais étiré, jamais recoloré, jamais répété dans la page. Le motif « anneaux » peut
être cité en CSS pur (état jour-calme) mais l'image ne sert qu'au header et aux icônes PWA.
`<meta name="theme-color">` doit passer à `#131210` (sombre) — prévoir la variante
`media="(prefers-color-scheme: light)"` à `#F0EEE6`.

## 7. Micro-interactions (toutes dans le CSS, sobres)

- **Arrivée des cartes** : fondu + montée 8px, cascade 55ms (`style="--i:n"` posé par le JS).
- **Dépliage** : `.tw-fold` grid `0fr→1fr`, 320ms — pas de JS de mesure de hauteur.
- **Copie** : tap sur `.tw-paste` → `.is-copied` 1.2s (bord vert, « ✓ copié », petit pop).
- **`prefers-reduced-motion`** : tout est coupé automatiquement.

## 8. Dette à purger pendant la refonte (bloquant offline)

`index.html` charge aujourd'hui Google Fonts + Tabler Icons via CDN : **à retirer** (la PWA
doit vivre sans réseau ; le service worker `sw.v1.js` ne peut pas les garantir). Les icônes
passent en glyphes Unicode (★ ✓ ⧉ ▾ — déjà intégrés aux composants) ou en SVG inline.
`pwa/styles.css` (clair-d'abord) est remplacé par `pwa/design-system.css` (sombre-d'abord).
