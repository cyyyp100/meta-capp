// filePicker.ts — Le sélecteur de fichier natif, simulé (partagé par les specs).

import type { Page } from "@playwright/test";

/**
 * Le sélecteur de fichier natif passe par le pont pywebview, absent d'un
 * navigateur. On l'implante avant le chargement de la page, exactement comme la
 * coque de bureau le fait : le frontend obtient un CHEMIN, le backend lit le
 * fichier côté serveur (voir src/api/platform.ts).
 */
export async function stubDesktopFilePicker(page: Page, path: string) {
  await page.addInitScript((p) => {
    (window as unknown as Record<string, unknown>).pywebview = {
      api: { pick_pdf: async () => p },
    };
  }, path);
}
