// csp.spec.ts — La CSP du serveur (S9, nwol/server/security.py) tient, et ne casse rien.
//
// Deux affirmations qui ne valent que dans un vrai navigateur :
//   1. l'application tourne sans AUCUNE violation — un script inline oublié, une
//      police ou une image d'une source non prévue se verraient ici ;
//   2. une injection HTML ne devient pas du JavaScript. C'est la raison d'être de
//      la CSP : dans la coque de bureau, un script qui s'exécute parle au pont
//      natif pywebview.

import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const FIXTURE = fileURLToPath(new URL("./fixtures/echantillon.pdf", import.meta.url));

const violations = (page: Page) =>
  page.evaluate(() => (window as unknown as { __cspViolations: string[] }).__cspViolations);

test.describe("Content-Security-Policy", () => {
  test.beforeEach(async ({ page }) => {
    await page.request.post("/api/preferences", { data: { tour_done: true } });
    // Posé avant tout script de la page : aucune violation n'y échappe.
    await page.addInitScript(() => {
      const w = window as unknown as { __cspViolations: string[] };
      w.__cspViolations = [];
      document.addEventListener("securitypolicyviolation", (e) => {
        w.__cspViolations.push(`${e.effectiveDirective} ${e.blockedURI}`);
      });
    });
  });

  test("l'application tourne sans violation, lecteur compris", async ({ page }) => {
    const response = await page.goto("/");
    expect(response?.headers()["content-security-policy"]).toContain("script-src 'self'");
    await expect(page.getByRole("navigation")).toBeVisible();
    // L'amorce du thème vient de /theme-boot.js, plus d'un script inline.
    await expect(page.locator("html")).toHaveAttribute("data-theme", /^(light|dark)$/);

    // Le lecteur : images de page servies par l'API et WebSocket du panneau.
    const imported = await page.request.post("/api/library/import", { data: { path: FIXTURE } });
    expect(imported.ok()).toBeTruthy();
    const { id } = await imported.json();
    await page.goto(`/reader/${id}`);
    const firstImage = page.locator("[data-page]").first().locator("img");
    await expect
      .poll(() => firstImage.evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 })
      .toBeGreaterThan(0);

    for (const path of ["/stats", "/stats/progress", "/flashcards", "/settings"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
    }

    expect(await violations(page)).toEqual([]);
  });

  test("une injection HTML ne s'exécute pas", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      const probe = document.createElement("div");
      probe.innerHTML = '<img src="data:," onerror="window.__pwned = 1">';
      document.body.appendChild(probe);
    });

    // La violation est l'événement qui prouve que le navigateur a tranché.
    await expect.poll(async () => (await violations(page)).length).toBeGreaterThan(0);
    expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
  });
});
