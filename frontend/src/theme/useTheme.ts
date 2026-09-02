// useTheme.ts — Thème clair/sombre/système, source unique.
//
// L'état vivait dans un `useState` d'AppLayout : personne d'autre ne pouvait le
// lire, alors que le Toaster (rendu en portail, hors de l'arbre) en a besoin.
// Même patron que `useLangStore` (src/i18n) : un store Zustand qui écrit aussi
// l'effet de bord (attribut sur <html> + persistance), pour qu'il n'existe
// qu'une seule façon de changer de thème.
//
// TROIS entrées, un seul chemin de sortie (`apply`) :
//   * la bascule de la barre latérale et l'écran Réglages appellent `setTheme` ;
//   * la barre de menu native émet `metacapp:theme` (le menu vit côté Python,
//     il ne peut pas toucher le store autrement) ;
//   * l'OS, quand le choix est « système ».
//
// La persistance est DOUBLE, et ce n'est pas une redondance :
//   * `localStorage` est lu par le script inline d'`index.html` AVANT le premier
//     rendu — c'est ce qui évite le flash de thème clair au démarrage ;
//   * `app_settings` (via `/api/preferences`) survit à une restauration de
//     sauvegarde et à un changement de machine, ce que le stockage du webview
//     ne fait pas. Le serveur est l'autorité au chargement, le localStorage
//     n'est qu'un cache d'amorçage.
import { create } from "zustand";

import { api } from "../api/client";

/** Ce que l'utilisateur CHOISIT. « system » n'est pas un rendu, c'est une règle. */
export type ThemeChoice = "light" | "dark" | "system";
/** Ce qui finit sur <html data-theme>. */
export type Theme = "light" | "dark";

const STORAGE_KEY = "metacapp-theme";

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function resolveTheme(choice: ThemeChoice): Theme {
  return choice === "system" ? systemTheme() : choice;
}

function readInitial(): ThemeChoice {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "light" || saved === "dark" || saved === "system") return saved;
  // Le script inline d'index.html a déjà posé un attribut : on le relit plutôt
  // que de dupliquer la règle de repli.
  const fromDom = document.documentElement.dataset.theme;
  return fromDom === "dark" ? "dark" : "light";
}

function apply(choice: ThemeChoice): Theme {
  const resolved = resolveTheme(choice);
  document.documentElement.dataset.theme = resolved;
  try {
    localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // Navigation privée / stockage refusé : le thème reste valable pour la session.
  }
  return resolved;
}

interface ThemeState {
  /** Le choix de l'utilisateur (peut valoir "system"). */
  choice: ThemeChoice;
  /** Le thème effectivement rendu — c'est lui que lisent les composants. */
  theme: Theme;
  setTheme: (choice: ThemeChoice, opts?: { persist?: boolean }) => void;
  toggleTheme: () => void;
}

const initialChoice = readInitial();

export const useThemeStore = create<ThemeState>((set, get) => ({
  choice: initialChoice,
  theme: apply(initialChoice),
  setTheme: (choice, opts) => {
    set({ choice, theme: apply(choice) });
    // `persist: false` sert au chargement initial (le serveur nous DIT déjà le
    // choix stocké) : le réécrire immédiatement serait un aller-retour pour rien.
    if (opts?.persist !== false) {
      void api.setPreferences({ theme: choice }).catch(() => undefined);
    }
  },
  // La bascule rapide reste binaire : depuis « système », on part sur le
  // contraire de ce qui est affiché, ce qui est ce qu'attend quelqu'un qui
  // clique sur une lune ou un soleil.
  toggleTheme: () => get().setTheme(get().theme === "light" ? "dark" : "light"),
}));

// Suivi de l'OS tant que le choix est « système ». Abonnement posé une fois,
// au chargement du module : il n'appartient à aucun composant.
window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
  const { choice, setTheme } = useThemeStore.getState();
  if (choice === "system") setTheme("system", { persist: false });
});

// Barre de menu native (« Affichage ▸ Thème clair/sombre »). Elle ne peut pas
// appeler le store : elle émet cet événement, et c'est le store qui décide.
window.addEventListener("metacapp:theme", (event) => {
  const detail = (event as CustomEvent<string>).detail;
  if (detail === "light" || detail === "dark" || detail === "system") {
    useThemeStore.getState().setTheme(detail);
  }
});
