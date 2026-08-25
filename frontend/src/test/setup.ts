// setup.ts — Amorçage commun des tests vitest (jsdom).
//
// Chargé par `vite.config.ts:test.setupFiles`, donc AVANT chaque fichier de test.

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom n'implémente pas matchMedia. Sans ce bouchon, tout composant qui
// interroge une media query — `prefers-reduced-motion` via Motion, ou un
// `useMediaQuery` — lève au premier rendu.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

// Selon la version de jsdom, `localStorage` peut être absent ou incomplet. Or
// plusieurs stores Zustand (thème, langue) le lisent DÈS L'IMPORT du module :
// sans ce filet, les fichiers de test échouent à la collecte, avant tout rendu.
if (typeof localStorage === "undefined" || typeof localStorage.getItem !== "function") {
  const store = new Map<string, string>();
  const shim: Storage = {
    get length() {
      return store.size;
    },
    key: (i) => [...store.keys()][i] ?? null,
    getItem: (k) => store.get(k) ?? null,
    setItem: (k, v) => void store.set(k, String(v)),
    removeItem: (k) => void store.delete(k),
    clear: () => store.clear(),
  };
  Object.defineProperty(window, "localStorage", { value: shim, configurable: true });
  Object.defineProperty(window, "sessionStorage", { value: shim, configurable: true });
}

// Radix (donc shadcn) mesure ses flottants avec ResizeObserver, absent de jsdom.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// Radix appelle scrollIntoView à l'ouverture d'un Select ; jsdom ne le définit pas.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// jsdom ne connaît pas l'API Pointer Events, sur laquelle Radix s'appuie pour
// distinguer souris et tactile. userEvent la sollicite dès qu'on ouvre un menu.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

// Testing Library démonte l'arbre entre deux tests : sans cela, les portails
// (Dialog, Tooltip) s'empilent dans document.body d'un test à l'autre.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
