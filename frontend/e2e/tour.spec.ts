// tour.spec.ts — Abandonner la visite guidée, à n'importe quelle étape.
//
// « Passer la visite » doit ramener à l'accueil, sans le document de
// démonstration, où que l'on soit dans le parcours. Abandonnée dans le lecteur,
// elle laissait l'écran tel quel : le sas d'entrée de la démo restait affiché
// et « Continuer » ouvrait un document que la visite venait de rendre.

import { expect, test, type Page } from "@playwright/test";

import { TOUR_STEPS } from "../src/features/tour/steps";

async function libraryIds(page: Page): Promise<number[]> {
  const docs = (await (await page.request.get("/api/library/documents")).json()) as { id: number }[];
  return docs.map((d) => d.id).sort((a, b) => a - b);
}

/** Clique « Suivant » jusqu'à l'étape demandée, repérée par son compteur. */
async function advanceTo(page: Page, id: string) {
  const index = TOUR_STEPS.findIndex((s) => s.id === id);
  const counter = (n: number) => page.getByText(`${n} / ${TOUR_STEPS.length}`, { exact: false });
  for (let n = 1; n <= index; n++) {
    await expect(counter(n)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: /^(suivant|next)$/i }).click();
  }
  await expect(counter(index + 1)).toBeVisible({ timeout: 15_000 });
}

test.describe("Passer la visite", () => {
  // Une étape par chapitre, plus le sas d'entrée où l'abandon restait coincé.
  for (const stepId of ["doc-card", "entry-sas", "clikoda-answer", "rest-sas", "profil"]) {
    test(`ramène à l'accueil sans la démo, depuis « ${stepId} »`, async ({ page }) => {
      const before = await libraryIds(page);
      await page.request.post("/api/preferences", { data: { tour_done: false } });
      await page.goto("/");

      await advanceTo(page, stepId);
      await page.getByRole("button", { name: /passer la visite|skip the tour/i }).click();

      await expect(page).toHaveURL(/\/$/);
      await expect(page.getByRole("button", { name: /passer la visite|skip the tour/i })).toHaveCount(0);
      // Le document emprunté est rendu, et la grille ne l'affiche plus.
      await expect.poll(() => libraryIds(page)).toEqual(before);
      await expect(page.locator(".doc-card")).toHaveCount(before.length);
    });
  }
});
