/* Où la PWA lit le radar.
   Ordre : data/radar.json (généré par la routine du matin) -> data/radar.demo.json (repli).
   En local comme en prod (GitHub Pages), on lit des fichiers relatifs — pas de serveur.
   Si un jour on ajoute un serveur de push, on le branchera ici. */
(function () {
  window.VEILLE_SOURCES = ["data/radar.json", "data/radar.demo.json"];
})();
