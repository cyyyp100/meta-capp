// playwright.config.ts — Parcours de bout en bout contre le VRAI backend.
//
// Le bundle compilé est servi par FastAPI lui-même (server/app.py monte
// frontend/dist sur `/` quand il existe) : exactement le montage de production.
//
// On a d'abord essayé `vite preview` + proxy /api, et la garde S1 a répondu 403 —
// à raison : `LocalOnlyGuard` n'accepte que les origines 8756 et 5173, et un
// preview sur 4173 est bien une origine étrangère. Passer par FastAPI supprime
// le problème au lieu de l'autoriser, et teste le chemin réellement livré.
//
// Ollama n'est pas requis : le backend a des chemins de repli déjà couverts par
// nwol/tests/server/test_llm_fallback.py. Les scénarios n'affirment jamais rien
// sur le CONTENU généré, seulement sur l'état de l'interface.

import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const BASE_URL = "http://127.0.0.1:8756";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // un seul écrivain SQLite côté backend (mono-processus par conception)
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["html", { open: "never" }], ["list"]] : [["list"]],

  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // La coque est une fenêtre de bureau : on teste à une taille réaliste, pas
    // au 1280x720 par défaut.
    viewport: { width: 1440, height: 900 },
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: {
    // L'app attend l'env conda `nwol` (voir CLAUDE.md). En CI il n'y a pas de
    // conda et `python` suffit ; en local on passe l'interpréteur de l'env.
    command: `${process.env.NWOL_PYTHON ?? "python"} -m server.main`,
    cwd: "../nwol",
    url: `${BASE_URL}/api/health`,
    // Toujours relancer : le serveur fige ses variables d'environnement au
    // démarrage (base, racines d'import). Réutiliser une instance lancée avec
    // un autre environnement donne des échecs incompréhensibles.
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      NWOL_DISABLE_CONDA_REEXEC: "1",
      // Base isolée : les scénarios importent des documents, ils ne doivent pas
      // écrire dans la bibliothèque réelle de l'utilisateur.
      NWOL_DB_PATH: fileURLToPath(new URL("./e2e/.tmp/e2e.db", import.meta.url)),
      // Garde S2 : seuls les fichiers sous ces racines sont importables.
      NWOL_IMPORT_ROOTS: fileURLToPath(new URL("./e2e/fixtures", import.meta.url)),
    },
  },
});
