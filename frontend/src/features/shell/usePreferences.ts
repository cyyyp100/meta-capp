// usePreferences.ts — Les réglages d'application, côté client.
//
// Une seule requête (`GET /api/preferences`) sert le bloc profil de la barre
// latérale, l'écran Réglages et la page de mise à jour. React Query en garde le
// cache ; chaque écriture le remplace par la réponse du serveur plutôt que de
// deviner l'état résultant.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { api } from "@/api/client";
import type { PreferenceKey, PreferencesPayload } from "@/api/client";
import { useThemeStore } from "@/theme/useTheme";

export const PREFERENCES_KEY = ["preferences"] as const;

export function usePreferences() {
  return useQuery({ queryKey: PREFERENCES_KEY, queryFn: api.preferences });
}

export function useSetPreference() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<Record<PreferenceKey, string | boolean>>) =>
      api.setPreferences(patch),
    onSuccess: (result) => {
      // On réécrit le cache avec ce que le SERVEUR a retenu : une valeur refusée
      // ou normalisée doit se voir dans l'interface, pas être supposée.
      queryClient.setQueryData<PreferencesPayload | undefined>(PREFERENCES_KEY, (previous) =>
        previous ? { ...previous, preferences: result.preferences } : previous,
      );
    },
  });
}

export function useSetUserName() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.setUserName(name),
    onSuccess: async (result) => {
      queryClient.setQueryData<PreferencesPayload | undefined>(PREFERENCES_KEY, (previous) =>
        previous ? { ...previous, user: result.user } : previous,
      );
      // Le nom s'affiche aussi sur la page Profil, servie par un autre endpoint.
      await queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

/**
 * Aligne le thème local sur celui que le serveur a stocké, une fois, au
 * démarrage.
 *
 * Le script inline d'`index.html` a déjà posé un thème depuis `localStorage`
 * pour éviter le flash — mais ce stockage appartient au webview : il ne survit
 * ni à une restauration de sauvegarde, ni à un changement de machine.
 * `app_settings` est l'autorité, et c'est ici qu'on la fait valoir.
 *
 * `persist: false` : on applique ce que le serveur a dit, on ne le lui renvoie
 * pas — sinon chaque démarrage écrirait une préférence que personne n'a changée.
 */
export function useThemeFromServer(payload: PreferencesPayload | undefined): void {
  const setTheme = useThemeStore((s) => s.setTheme);
  const stored = payload?.preferences.theme;
  useEffect(() => {
    if (stored === "light" || stored === "dark" || stored === "system") {
      setTheme(stored, { persist: false });
    }
  }, [stored, setTheme]);
}
