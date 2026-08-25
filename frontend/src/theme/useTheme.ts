// useTheme.ts — Thème clair/sombre, source unique.
//
// L'état vivait dans un `useState` d'AppLayout : personne d'autre ne pouvait le
// lire, alors que le Toaster (rendu en portail, hors de l'arbre) en a besoin.
// Même patron que `useLangStore` (src/i18n) : un store Zustand qui écrit aussi
// l'effet de bord (attribut sur <html> + localStorage), pour qu'il n'existe
// qu'une seule façon de changer de thème.
//
// La valeur initiale est déjà posée sur <html> par le script inline d'index.html
// (avant le premier rendu, pour éviter un flash) : on la relit ici plutôt que de
// dupliquer la règle de repli.

import { create } from "zustand";

export type Theme = "light" | "dark";

const STORAGE_KEY = "metacapp-theme";

function readInitial(): Theme {
  const fromDom = document.documentElement.dataset.theme;
  if (fromDom === "light" || fromDom === "dark") return fromDom;
  const saved = localStorage.getItem(STORAGE_KEY);
  // Démarrage en clair par défaut : on n'hérite pas du thème système sombre.
  return saved === "dark" ? "dark" : "light";
}

function apply(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Navigation privée / stockage refusé : le thème reste valable pour la session.
  }
}

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: readInitial(),
  setTheme: (theme) => {
    apply(theme);
    set({ theme });
  },
  toggleTheme: () => get().setTheme(get().theme === "light" ? "dark" : "light"),
}));
