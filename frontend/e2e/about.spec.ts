// about.spec.ts — Réglages ▸ Aide ▸ À propos : IA, confidentialité, licences.
//
// Les mentions des licences tierces ne sont générées que par la release (ou à la
// main, `scripts/third_party_notices.py`) : selon le checkout, la modale montre
// leur texte ou dit comment les produire. Les deux sont des issues normales ;
// ce qui ne l'est pas, c'est une modale vide ou un lien parti hors de l'app.

import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.request.post("/api/preferences", { data: { tour_done: true, theme: "light", lang: "fr" } });
});

test("la carte À propos dit que Clikoda est une IA et ouvre les licences dans l'app", async ({ page }) => {
  await page.goto("/settings/about");

  await expect(page.getByText(/Clikoda est une IA/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Politique de confidentialité" })).toHaveAttribute(
    "href",
    "https://github.com/cyyyp100/meta-capp/blob/main/PRIVACY.md",
  );

  await page.getByRole("button", { name: "Licences des composants tiers" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/Meta-Capp — mentions des composants tiers|scripts\/third_party_notices\.py/)).toBeVisible();
  await page.screenshot({ path: "test-results/about.png" });
});
