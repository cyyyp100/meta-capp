/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En dev, le frontend tourne sur :5173 et proxy les appels /api vers le
// serveur FastAPI local. En prod (pywebview/Tauri), FastAPI sert directement
// le bundle compilé et il n'y a pas de proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8756",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
  },
});
