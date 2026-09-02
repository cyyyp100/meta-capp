// useDisplayPreferences.ts — Densité et taille du texte, posées sur <html>.
//
// Même patron que le thème : un attribut sur l'élément racine, et TOUTE la
// conséquence visuelle dans `tokens.css`. Aucun composant ne lit ces réglages —
// s'ils devaient être consultés en JS, chaque écran finirait par en tirer ses
// propres marges, et on aurait autant de définitions de « compact » que d'écrans.
import { useEffect } from "react";

import type { PreferencesPayload } from "@/api/client";

export function useDisplayPreferences(payload: PreferencesPayload | undefined): void {
  const density = payload?.preferences.density;
  const textSize = payload?.preferences.text_size;

  useEffect(() => {
    const root = document.documentElement;
    // On retire l'attribut à la valeur par défaut plutôt que de l'écrire :
    // `[data-density="comfortable"]` n'a aucune règle, et un attribut sans règle
    // est une invitation à en ajouter une ailleurs.
    if (density && density !== "comfortable") root.dataset.density = density;
    else delete root.dataset.density;

    if (textSize && textSize !== "normal") root.dataset.textSize = textSize;
    else delete root.dataset.textSize;
  }, [density, textSize]);
}
