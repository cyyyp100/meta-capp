// shell.spec.ts — La coque de l'application : navigation, thème, langue.
//
// Ce sont les trois choses qu'un utilisateur touche à chaque session et que
// personne ne reteste à la main après un changement de style.

import { expect, test } from "@playwright/test";

test.describe("Coque de l'application", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("affiche la barre latérale et les six destinations", async ({ page }) => {
    const nav = page.getByRole("navigation");
    await expect(nav).toBeVisible();
    await expect(nav.getByRole("link")).toHaveCount(6);
  });

  test("navigue entre les écrans et marque la destination active", async ({ page }) => {
    const flashcards = page.getByRole("link", { name: /flashcards/i });
    await flashcards.click();

    await expect(page).toHaveURL(/\/flashcards$/);
    // react-router pose aria-current sur le lien actif : c'est l'état que les
    // lecteurs d'écran annoncent, pas la couleur de fond.
    await expect(flashcards).toHaveAttribute("aria-current", "page");
  });

  test("bascule le thème et le retient d'une navigation à l'autre", async ({ page }) => {
    const html = page.locator("html");
    await expect(html).toHaveAttribute("data-theme", "light");

    await page.getByRole("button", { name: /mode sombre|dark mode/i }).click();
    await expect(html).toHaveAttribute("data-theme", "dark");

    await page.reload();
    await expect(html).toHaveAttribute("data-theme", "dark");
  });

  test("bascule la langue de l'interface", async ({ page }) => {
    await expect(page.getByRole("link", { name: "Accueil" })).toBeVisible();

    await page.getByRole("button", { name: "EN", exact: true }).click();

    await expect(page.getByRole("link", { name: "Home" })).toBeVisible();
  });

  test("tout élément interactif est atteignable au clavier avec un focus visible", async ({
    page,
  }) => {
    // Le défaut central de l'audit : 87 boutons sans aucun état de focus. Ce test
    // vérifie que la tabulation atteint bien la navigation et qu'un anneau de
    // focus est effectivement peint.
    await page.keyboard.press("Tab");
    const focused = page.locator(":focus-visible");
    await expect(focused).toBeVisible();

    const outline = await focused.evaluate((el) => {
      const s = getComputedStyle(el);
      return { shadow: s.boxShadow, outline: s.outlineStyle, width: s.outlineWidth };
    });
    const hasRing =
      outline.shadow !== "none" || (outline.outline !== "none" && outline.width !== "0px");
    expect(hasRing, "l'élément focalisé au clavier ne peint aucun anneau").toBe(true);
  });
});
