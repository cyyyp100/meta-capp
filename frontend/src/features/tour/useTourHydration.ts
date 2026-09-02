// useTourHydration.ts — Charge l'état de la visite depuis les préférences.
//
// Séparé du store pour la même raison que `useThemeFromServer` : le store est
// synchrone et sans réseau, l'hydratation est un effet React branché sur la
// requête que la barre latérale fait déjà.
import { useEffect } from "react";

import type { PreferencesPayload } from "@/api/client";

import { toStep, useTour } from "./useTour";

export function useTourHydration(payload: PreferencesPayload | undefined): void {
  const hydrate = useTour((s) => s.hydrate);
  const done = payload?.preferences.tour_done;
  const step = payload?.preferences.tour_step;

  useEffect(() => {
    if (done === undefined) return;
    hydrate(done === "true", toStep(step));
  }, [done, step, hydrate]);
}
