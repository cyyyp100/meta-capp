/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En dev, le frontend tourne sur :5173 et proxy les appels /api vers le
// serveur FastAPI local. En prod (pywebview/Tauri), FastAPI sert directement
// le bundle compilé et il n'y a pas de proxy.
const apiProxy = {
  "/api": {
    target: "http://127.0.0.1:8756",
    changeOrigin: true,
    ws: true, // le lecteur passe par un WebSocket (/api/reader/{id}/stream)
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // `@/` = racine des sources. Convention shadcn/ui, doublée dans tsconfig.json.
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: apiProxy,
  },
  // `vite preview` n'hérite PAS de `server.proxy` : sans ce bloc, les parcours
  // Playwright — qui tournent sur le bundle compilé, pas sur le serveur de dev —
  // verraient tous leurs appels /api partir dans le vide.
  preview: {
    port: 4173,
    proxy: apiProxy,
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Vitest et Playwright exportent tous deux un `test` : sans ce cloisonnement,
    // vitest ramasse les specs de `e2e/` et échoue sur `test.describe()`.
    // Les tests de composants vivent dans `src/`, les parcours dans `e2e/`.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
