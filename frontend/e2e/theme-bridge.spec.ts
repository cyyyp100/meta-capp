// theme-bridge.spec.ts — Le pont entre tokens.css et Tailwind (`@theme inline`).
//
// Ce pont est silencieux quand il casse : rien n'échoue au type-check ni au
// build. Un alias mal nommé se contente de produire une valeur absurde. C'est
// arrivé pendant la migration — `--spacing-md: 14px` détournait `max-w-md`, et
// comme dialog.tsx porte `sm:max-w-lg`, TOUS les dialogues faisaient 22px.
//
// Ces tests peignent réellement les utilitaires dans un navigateur et vérifient
// que les valeurs restent plausibles.

import { expect, test } from "@playwright/test";

/** Applique des classes sur un élément jetable et rend son style calculé. */
async function computed(page: import("@playwright/test").Page, classes: string) {
  return page.evaluate((cls) => {
    const el = document.createElement("div");
    el.className = cls;
    document.body.appendChild(el);
    const s = getComputedStyle(el);
    const out = {
      maxWidth: s.maxWidth,
      width: s.width,
      padding: s.paddingTop,
      borderRadius: s.borderTopLeftRadius,
      background: s.backgroundColor,
      color: s.color,
      boxShadow: s.boxShadow,
      fontFamily: s.fontFamily,
    };
    el.remove();
    return out;
  }, classes);
}

test.describe("Pont tokens.css -> Tailwind", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("les utilitaires de largeur ne sont pas détournés par des alias d'espacement", async ({
    page,
  }) => {
    // `max-w-lg` doit rester une largeur de conteneur (32rem = 512px), jamais
    // une valeur d'espacement. C'est la classe qui dimensionne les dialogues.
    const lg = await computed(page, "max-w-lg");
    expect(parseFloat(lg.maxWidth)).toBeGreaterThan(300);

    const md = await computed(page, "max-w-md");
    expect(parseFloat(md.maxWidth)).toBeGreaterThan(300);

    const xs = await computed(page, "max-w-xs");
    expect(parseFloat(xs.maxWidth)).toBeGreaterThan(150);
  });

  test("les couleurs de marque pointent bien sur les tokens", async ({ page }) => {
    const brand = await computed(page, "bg-brand");
    // --accent clair = #2f7d8c
    expect(brand.background).toBe("rgb(47, 125, 140)");

    const surface = await computed(page, "bg-surface");
    expect(surface.background).toBe("rgb(255, 255, 255)");
  });

  test("les rayons et les élévations résolvent (pas de référence circulaire)", async ({ page }) => {
    const r = await computed(page, "rounded-sm");
    expect(r.borderRadius).toBe("10px"); // --radius-sm

    const e = await computed(page, "shadow-e2");
    expect(e.boxShadow).not.toBe("none");
    expect(e.boxShadow).not.toContain("var(");
  });

  test("le thème sombre bascule sans variant dark: explicite", async ({ page }) => {
    const before = await computed(page, "bg-background");
    expect(before.background).toBe("rgb(244, 247, 248)"); // --bg clair

    await page.evaluate(() => {
      document.documentElement.dataset.theme = "dark";
    });

    const after = await computed(page, "bg-background");
    expect(after.background).toBe("rgb(17, 24, 28)"); // --bg sombre
  });

  test("le texte posé sur l'accent garde un contraste suffisant dans les deux thèmes", async ({
    page,
  }) => {
    // --on-accent est blanc en clair et encre foncée en sombre : sans cette
    // bascule, du blanc sur l'accent éclairci du thème sombre passerait sous le
    // seuil lisible.
    const light = await computed(page, "text-primary-foreground");
    expect(light.color).toBe("rgb(255, 255, 255)");

    await page.evaluate(() => {
      document.documentElement.dataset.theme = "dark";
    });
    const dark = await computed(page, "text-primary-foreground");
    expect(dark.color).toBe("rgb(13, 21, 24)");
  });
});
