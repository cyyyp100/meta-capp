// shell.spec.ts — La coque de l'application : navigation, thème, langue.
//
// Ce sont les trois choses qu'un utilisateur touche à chaque session et que
// personne ne reteste à la main après un changement de style.

import { expect, test } from "@playwright/test";

test.describe("Coque de l'application", () => {
  test.beforeEach(async ({ page }) => {
    // La visite guidée du premier lancement pose un voile sur l'écran : c'est le
    // comportement voulu, et c'est exactement ce qui rendrait ces scénarios
    // ininterprétables. On la déclare faite via l'API — la même que celle que
    // « Passer la visite » utilise, donc on ne teste pas un chemin fictif.
    await page.request.post("/api/preferences", { data: { tour_done: true } });
    await page.goto("/");
  });

  test("affiche la barre latérale et ses six destinations", async ({ page }) => {
    const nav = page.getByRole("navigation");
    await expect(nav).toBeVisible();
    // Six et non sept : « Progression » n'est pas une destination autonome, elle
    // vit sous /stats/progress et s'ouvre depuis le bas du profil.
    await expect(nav.getByRole("link")).toHaveCount(6);
  });

  test("la progression s'ouvre depuis le bas du profil, et on en revient", async ({ page }) => {
    await page.goto("/stats");
    await page.getByRole("link", { name: /ma progression|my progress/i }).click();

    await expect(page).toHaveURL(/\/stats\/progress$/);
    await page.getByRole("link", { name: /retour au profil|back to profile/i }).click();
    await expect(page).toHaveURL(/\/stats$/);
  });

  test("navigue entre les écrans et marque la destination active", async ({ page }) => {
    const flashcards = page.getByRole("link", { name: /flashcards/i });
    await flashcards.click();

    await expect(page).toHaveURL(/\/flashcards$/);
    // react-router pose aria-current sur le lien actif : c'est l'état que les
    // lecteurs d'écran annoncent, pas la couleur de fond.
    await expect(flashcards).toHaveAttribute("aria-current", "page");
  });

  test("bascule le thème depuis le bloc profil et le retient", async ({ page }) => {
    const html = page.locator("html");
    await expect(html).toHaveAttribute("data-theme", "light");

    // Le bouton de thème nu du pied de barre a été remplacé par le menu profil :
    // il faut désormais l'ouvrir pour l'atteindre.
    await page.getByRole("button", { name: /menu du profil|profile menu/i }).click();
    await page.getByRole("menuitem", { name: /mode sombre|dark mode/i }).click();
    await expect(html).toHaveAttribute("data-theme", "dark");

    await page.reload();
    await expect(html).toHaveAttribute("data-theme", "dark");

    // Le thème est persisté côté serveur : sans cette remise à zéro, il
    // contaminerait les scénarios suivants (même base pour toute la campagne).
    await page.request.post("/api/preferences", { data: { theme: "light" } });
  });

  test("le thème choisi survit à un vidage du stockage du navigateur", async ({ page }) => {
    // C'est la raison d'être du passage à `app_settings` : le localStorage du
    // webview ne survit ni à une restauration de sauvegarde ni à un changement
    // de machine. Le serveur fait autorité.
    await page.request.post("/api/preferences", { data: { theme: "dark" } });
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  });

  test("bascule la langue depuis les Réglages", async ({ page }) => {
    await expect(page.getByRole("link", { name: "Accueil" })).toBeVisible();

    // Le segmenté FR/EN du pied de barre vit maintenant dans /settings/language.
    await page.goto("/settings/language");
    await page.getByRole("button", { name: "EN", exact: true }).click();

    await expect(page.getByRole("link", { name: "Home" })).toBeVisible();

    // Remise en français : la langue est persistée côté serveur, elle
    // contaminerait les scénarios suivants.
    await page.getByRole("button", { name: "FR", exact: true }).click();
    await expect(page.getByRole("link", { name: "Accueil" })).toBeVisible();
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
