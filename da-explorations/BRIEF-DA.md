# BRIEF DA — REFONTE THE WIRE

Brief créatif. Trois directions artistiques concourent. Le jury tranche sur les critères du §6.
Matière : 4 fouilles OSINT (marché, avant-garde) + audit du front existant (`index.html`, `pwa/design-system.css`, `pwa/app.js`, `data/radar.demo.json`).

---

## 1. Positionnement — une phrase

**The Wire n'est pas un dashboard, c'est un ordre de mission : chaque matin à 10h, un verdict chiffré, un geste, un euro — lisible à bout de bras, exécutable au pouce.**

Corollaire : tout pixel qui ne sert pas le verdict, le geste ou la confiance est du bruit.

---

## 2. Les 5 jobs du design, classés par impact cash

**J1 — Déclencher le « go ».** Le seul geste qui génère du cash. L'action doit posséder la SEULE couleur vive de l'interface, réservée, jamais diluée (modèle : Linear, acid-lime #e4f222 réservé ; Perplexity, turquoise unique). Aujourd'hui le geste « go » n'a même pas de représentation visuelle dans le PWA. Impact : direct, immédiat.

**J2 — Rendre le gain chiffré écrasant.** Le titre d'un move EST un gain (« ~290€ »). Ce chiffre doit dominer la carte façon score Whoop (~72pt, lisible à bout de bras — le choix qui a fait une boîte à 3,6 Md$) et façon Mercury/Ramp (UNE métrique incarne la promesse). Chiffres en ui-monospace tabulaire (TradingView : +23% de temps de lecture mesuré). Impact : Adam agit plus vite, plus souvent.

**J3 — Tenir les 20 secondes.** Architecture 3 tiers (Whoop) : tier 1 = verdict + do_now sans scroll ; tier 2 = steps au tap ; tier 3 = matière brute (paste). Hiérarchie éditoriale, pas chat-log (leçon Gemini « Neural Expressive », I/O 19 mai 2026 : info critique isolée en tête, secondaire scrollable dessous). Impact : le rituel du matin survit.

**J4 — Fabriquer la confiance factuelle.** Stats fraîcheur/coupe, ratios de contraste calculés, chiffres alignés, posture « véhicule pour des faits » (Perplexity). La confiance est la condition du « go » : un radar qui a l'air généré n'est pas cru, donc pas suivi (anti-modèle Rivalyze/Valona : dashboards abandonnés). Impact : rétention = cash récurrent.

**J5 — Montrer le pipeline au travail.** Après « go N », rendre visible l'état Fable→Sonnet (pattern agentique 2026 : Comet, Dia — montrer ce que l'agent fait, permettre l'override). Boucle fermée = Adam revient demain. Impact : différé mais structurel.

---

## 3. Ce que la DA actuelle rate — vérité crue

1. **C'est le look IA au pixel près.** Charbon chaud #131210 + terracotta #CC785C + serif d'accent = le cluster « beige-ification » catalogué comme tell du design génératif (Kompozy, DEV.to), rejeté par 45% des directeurs créatifs seniors pour du tier-1. Le diagnostic d'Adam est exact : ce n'est pas une nuance à corriger, c'est une famille à quitter.
2. **Propre ≠ identité.** Tokens rigoureux, contrastes calculés et annotés, a11y sérieuse — et zéro trait reconnaissable à 2 mètres. C'est un excellent template. Un template.
3. **Le chiffre est noyé.** Le gain « ~290€ » vit dans une phrase à 17px, même graisse que le reste (`--fs-title`). La seule donnée qui justifie le produit est typographiquement banalisée. Whoop met le verdict à 72pt ; The Wire le met en sous-titre.
4. **L'accent est partout, donc nulle part.** Terracotta sur do_now, insight, focus, paste hint, anneaux du radar + 6 ramps projet + or du badge star : la couleur code le projet (info secondaire) au lieu de coder la décision (info primaire). Aucune couleur n'appartient au « go ».
5. **Tout est carte.** Moves, skill, banner : même gabarit radius 16px + filet gauche 3px = « barre d'accent sur carte arrondie », motif template listé dans les interdits. Aucune tension, aucun contraste de forme.
6. **La serif d'apparat signe l'IA, pas Adam.** La headline en ui-serif est exactement le geste « élégance générée » du cluster à fuir.

---

## 4. Le territoire créatif ouvert — l'espace vierge

Cartographie des références : Linear/Raycast tiennent le **dark discipliné + typo technique** (mais froid, SaaS d'équipe, desktop). Whoop tient la **compression en verdict massif** (mais fitness, pas décision d'action). Bloomberg tient le **statut par répétition** (40 ans d'historique — inaccessible et non-excuse pour ne pas moderniser). Perplexity tient le **neutre factuel invisible** (sans geste d'action). Granola tient l'**imperfection anti-lissé** (mais soft, notes). Les dashboards de veille (Rivalyze, Valona) ne tiennent rien : génériques, abandonnés.

**L'espace vierge : la dépêche actionnable.** Personne n'occupe le croisement (a) verdict massif lisible à bout de bras × (b) précision typographique système froide × (c) UN accent électrique propriété exclusive du geste « go » × (d) langage brutaliste-tactile (angles 0, filets 1px pleins, zéro ombre portée — 100% vanilla CSS, signal de précision humaine contre le lissé génératif). Le nom même du produit désigne ce territoire : **wire = fil de dépêche d'agence**. Le télégramme AP/Reuters, le ticket d'ordre, l'avis de mission — un genre visuel chargé d'urgence factuelle que AUCUNE référence étudiée n'exploite, et qui n'a jamais été modernisé en dark mobile-first. Deuxième gisement vierge : le **statut agentique visible** (Comet/Dia) n'a jamais été croisé avec un format mobile 20 secondes. Troisième levier différenciant : une **micro-imperfection assumée** (Granola) comme antidote au soupçon « généré par template » — un seul geste rugueux, pas un style.

Les trois directions doivent creuser ce territoire par des angles différents — pas le même moodboard en trois teintes.

---

## 5. Contraintes tech non négociables (audit)

- **Vanilla HTML/CSS/JS. Zéro build, zéro framework, zéro CDN, zéro requête externe.** La PWA vit 100% offline (service worker `sw.v1.js` à la racine, `pwa/manifest.json`) ; tout asset nouveau doit être précaché.
- **Fontes système uniquement** pour tout ce qui s'implémente : system-ui, ui-serif, ui-monospace, Segoe UI Variable, Cascadia Mono… Une fonte spécifique exigée par une direction = NOMMÉE (nom + licence + URL) dans son manifeste ; personne ne télécharge rien aujourd'hui, Adam décide.
- **Mobile-first 390px.** Lecture type : téléphone, 20 secondes, le matin. Cibles tactiles ≥ 44px (le CSS actuel le fait ; ne pas régresser).
- **Contrastes WCAG CALCULÉS, jamais estimés** : ≥ 4.5:1 texte, ≥ 3:1 UI non-textuelle, ratio annoté en commentaire à côté de chaque couleur (convention existante de `design-system.css` — à conserver).
- **Le schéma de données est roi** : la DA habille `data/radar.demo.json` tel quel (headline, moves{rank/star, projet, ramp, meta, title, pourquoi_maintenant, insight, do_now, steps{t,how,paste,done}, ensuite, aussi_pour}, skill_up, stats). Pas de champ inventé.
- **Thème sombre par défaut** ; variante claire automatique conservée OU dark-only argumenté dans le manifeste de direction.
- **Motion signifiante seulement** : 160–500ms, chaque animation mappée à un état (chargement, copie, dépliage, go, pipeline) ; `prefers-reduced-motion` respecté intégralement.
- **A11y existante = plancher** : aria-live, .visually-hidden, :focus-visible, fold retiré de l'ordre de tabulation.
- **Production intouchable** : `data/` en lecture seule, pas de commit, pas de Telegram, pas de poller.

---

## 6. Critères de jugement du jury — mesurables

1. **Test des 2 mètres** : screenshot 390px réduit à 15% — le gain chiffré du move star et la zone d'action restent identifiables. Proxy mesurable : le chiffre € du star ≥ 40px rendus ; l'accent d'action = élément coloré le plus saillant de l'écran.
2. **Test des 20 secondes** : sur viewport 390×844, verdict (gain) + do_now du star visibles SANS scroll.
3. **Unicité de l'accent** : la couleur d'action apparaît dans ≤ 2 familles de sélecteurs CSS (grep vérifiable). Toute fuite = pénalité.
4. **Zéro marqueur du cluster IA** : aucun token dans les familles interdites du §7 — vérification par inspection des variables CSS. Un seul marqueur = élimination.
5. **Contrastes prouvés** : 100% des paires texte/fond annotées avec ratio calculé ≥ 4.5:1 (≥ 3:1 UI). Un ratio manquant ou faux = défaut bloquant.
6. **Budget technique** : 0 requête externe (onglet réseau vide hors origine), 0 dépendance, offline au 2e chargement, pas de régression des cibles 44px.
7. **Signature propriétaire** : ≥ 3 traits nommables (un geste typographique systématique — feature-settings/tracking/tabular ; un motif graphique ; un comportement) qui survivent au test noir & blanc. Modèle : ss03 de Raycast — un réglage suffit à marquer.
8. **Motion auditée** : chaque animation justifiée par un état, durées 160–500ms, reduced-motion vérifié. Une animation décorative = pénalité.
9. **Le « go » existe** : la direction montre l'action « go N » et l'état du pipeline après tap (J1/J5). Absent = hors sujet.

---

## 7. Interdits anti-générique — élimination d'office

- Crème chaude (#F4F1EA et voisins) + serif d'apparat + accent terracotta — la DA actuelle. À tuer, pas à nuancer.
- Quasi-noir + unique pop acid-green ou vermillon (le raccourci « edgy » déjà saturé).
- Broadsheet à filets hairline + colonnes denses façon « journal du dimanche ».
- Hero en dégradé violet→bleu sur blanc.
- Inter / Space Grotesk comme choix « sûr » par défaut (et de toute façon : fontes système only).
- Emojis comme marqueurs de sections.
- Tout centré, rounded-lg partout, barre d'accent sur cartes arrondies.
- Ajouts issus des fouilles : glassmorphism/liquid glass, gradients par défaut, bento grid cliché, nostalgie Y2K, minimalisme « sans âme », maximalisme-bruit, animation gratuite, serif display fort-contraste utilisé par défaut (marqueur IA documenté).

**Épreuve finale : la direction doit être reconnaissable entre mille, à 2 mètres, sur un téléphone.**
