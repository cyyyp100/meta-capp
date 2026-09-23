// Applique le thème AVANT le premier rendu (sinon l'app clignote en clair
// au démarrage de quelqu'un qui l'a réglée en sombre). Le choix stocké
// peut valoir "system" : il faut alors résoudre contre l'OS ici même —
// attendre React, c'est déjà avoir affiché la mauvaise couleur.
//
// `localStorage` n'est qu'un CACHE d'amorçage : l'autorité est
// `app_settings` côté serveur (cf. src/theme/useTheme.ts), qui survit à
// une restauration de sauvegarde. Ce script ne fait que devancer la
// première réponse de l'API.
//
// Fichier séparé et non `<script>` inline : la CSP du serveur interdit tout
// script inline (nwol/server/security.py, S9). Chargé sans `defer` ni
// `type="module"` pour s'exécuter avant le premier rendu, comme avant.
(function () {
  var saved = null;
  try {
    saved = localStorage.getItem("metacapp-theme");
  } catch {
    // Stockage indisponible : on retombe sur le thème clair.
  }
  var dark =
    saved === "dark" ||
    (saved === "system" &&
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
})();
