// ESLint (flat config) — lint bloquant en CI. Règles : erreurs réelles
// (recommended JS/TS + hooks React), pas de style (le formatage reste libre).
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Règles strictes hooks v7 : avis de performance sur des patterns
      // préexistants (setState dans effets du Reader) — surfacés en warning,
      // à résorber au fil de l'eau plutôt qu'en refactor de masse risqué.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      // Le pont pywebview et quelques événements WS restent typés `any` : toléré
      // explicitement plutôt que contourné par des casts silencieux.
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
