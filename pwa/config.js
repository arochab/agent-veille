/* Où la PWA lit le radar.
   Ordre : data/radar.json (généré par la routine du matin) -> data/radar.demo.json (repli).
   En local comme en prod (GitHub Pages), on lit des fichiers relatifs — pas de serveur.
   Si un jour on ajoute un serveur de push, on le branchera ici. */
(function () {
  window.VEILLE_SOURCES = ["data/radar.json", "data/radar.demo.json"];

  /* État réel des go (VISION-ACTIVATION §2) : data/go_suivi.json est l'index
     dérivé produit par systeme/suivi_go.py (commits, events "fait"/"paye",
     confirmations d'Adam). Lu en same-origin, EXACTEMENT comme radar.json -
     zéro requête externe, zéro contact avec le poller réel. C'est une donnée
     PRIVÉE (data/* gitignored) : absente sur GitHub Pages public -> la section
     qui en dépend se masque, rien n'est inventé à la place. */
  window.SUIVI_SOURCES = ["data/_test_go_suivi_TEMP.json"];

  /* data/projets.json : SOURCE UNIQUE des noms d'affichage produit (ex.
     "serp-scraper" -> "BrandPulse") et des ramps couleur - ce fichier EST
     public (whitelisté dans .gitignore), donc toujours résolvable. Lookup
     texte pur (nom + ramp), aucun calcul d'état : si absent, le nom technique
     brut du champ "projet" s'affiche tel quel (jamais de valeur inventée). */
  window.PROJETS_SOURCES = ["data/projets.json"];
})();
