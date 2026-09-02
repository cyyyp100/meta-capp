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

/**
 * Contraste WCAG entre deux couleurs `rgb(...)` telles que le navigateur les
 * rend. Mesurer le RATIO plutôt que d'affirmer des valeurs littérales : une
 * palette a le droit de changer, la lisibilité non. Les assertions littérales
 * qui vivaient ici cassaient à chaque repalettage sans jamais rien attraper.
 */
function contrast(a: string, b: string): number {
  const luminance = (color: string) => {
    // Deux formats : `rgb(...)` (ce que rend le navigateur) et l'hexadécimal
    // d'un jeton lu directement. Les deux notations hexa comptent — le minifieur
    // CSS réécrit `#ffffff` en `#fff`, et n'accepter que la forme longue faisait
    // planter le test sur une couleur parfaitement valide.
    const hex = color.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    const [r, g, b2] = hex
      ? hex[1].length === 3
        ? [...hex[1]].map((c) => parseInt(c + c, 16))
        : [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16))
      : color.match(/\d+(\.\d+)?/g)!.slice(0, 3).map(Number);
    const channel = (v: number) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b2);
  };
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Écart de teinte (0-180°) entre deux couleurs. Deux remplissages peuvent
 *  contraster identiquement avec le fond et rester indiscernables l'un de
 *  l'autre : c'est la teinte qui le dit, pas le contraste. */
function hueGap(a: string, b: string): number {
  const hue = (color: string) => {
    const hex = color.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    const [r, g, bl] = hex
      ? hex[1].length === 3
        ? [...hex[1]].map((c) => parseInt(c + c, 16))
        : [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16))
      : color.match(/\d+(\.\d+)?/g)!.slice(0, 3).map(Number);
    const [rn, gn, bn] = [r / 255, g / 255, bl / 255];
    const max = Math.max(rn, gn, bn);
    const min = Math.min(rn, gn, bn);
    if (max === min) return 0;
    const d = max - min;
    const h =
      max === rn ? ((gn - bn) / d) % 6 : max === gn ? (bn - rn) / d + 2 : (rn - gn) / d + 4;
    return (h * 60 + 360) % 360;
  };
  const gap = Math.abs(hue(a) - hue(b));
  return Math.min(gap, 360 - gap);
}

/** Valeurs brutes de jetons `--x` sous un thème donné. */
async function readTokens(
  page: import("@playwright/test").Page,
  theme: "light" | "dark",
  names: string[],
): Promise<Record<string, string>> {
  return page.evaluate(
    ([t, keys]) => {
      document.documentElement.dataset.theme = t as string;
      const style = getComputedStyle(document.documentElement);
      const out: Record<string, string> = {};
      for (const key of keys as string[]) out[key] = style.getPropertyValue(key).trim();
      return out;
    },
    [theme, names] as const,
  );
}

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
    // Le thème est persisté côté SERVEUR depuis qu'il vit dans `app_settings` :
    // un scénario précédent qui l'a basculé en sombre le laisse ainsi pour tous
    // les suivants. Ces tests-ci affirment des VALEURS de jetons : ils doivent
    // partir d'un thème connu, et le dire plutôt que d'en hériter.
    await page.request.post("/api/preferences", {
      data: { tour_done: true, theme: "light" },
    });
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
    // --accent = #f59e0b (ambre doré) en thème CLAIR — c'est ce que mesure ce
    // test (le beforeEach force `light`). Le thème sombre en prend une version
    // assombrie et désaturée, #d98a19 : l'ambre plein brûlait sur le bleu nuit.
    // Ce qui reste vrai des deux côtés, c'est le RATIO, vérifié plus bas.
    expect(brand.background).toBe("rgb(245, 158, 11)");

    const surface = await computed(page, "bg-surface");
    expect(surface.background).toBe("rgb(255, 255, 255)");
  });

  test("le survol des menus reste BLEUTÉ, il ne prend pas la couleur de marque", async ({
    page,
  }) => {
    // L'identité est bleue à 80-90 % et l'orange ne sert qu'à attirer l'œil.
    // `--color-accent` est la surface de survol de shadcn (menus, onglet actif,
    // items de liste) : elle pointait sur `--accent-soft` par commodité, et
    // teintait donc en orange une bonne moitié des pixels de l'écran. Ce test
    // empêche quiconque de la rebrancher là par réflexe.
    const hover = await computed(page, "bg-accent");
    const [r, g, b] = hover.background.match(/\d+/g)!.map(Number);
    expect(b, "la surface de survol doit tirer vers le bleu, pas vers l'orange").toBeGreaterThan(r);
    expect(g).toBeGreaterThan(r - 20);
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
    expect(before.background).toBe("rgb(248, 250, 252)"); // --bg clair (#f8fafc)

    await page.evaluate(() => {
      document.documentElement.dataset.theme = "dark";
    });

    const after = await computed(page, "bg-background");
    expect(after.background).toBe("rgb(8, 13, 23)"); // --bg sombre (#080d17)
  });

  test("le texte posé sur l'accent garde un contraste suffisant dans les deux thèmes", async ({
    page,
  }) => {
    // Ce test affirmait des VALEURS littérales ("rgb(255,255,255)") : il cassait
    // à chaque changement de palette alors que ce qui compte n'a jamais changé.
    // Il mesure désormais le RATIO — la propriété qu'on veut réellement tenir,
    // et qui survivra à la prochaine identité.
    //
    // C'est ce test qui a attrapé le piège de cette palette : du blanc sur
    // #f97316 ne fait que 2,80:1. L'encre est donc le bleu nuit, et elle reste
    // la même dans les deux thèmes — 8,72:1 sur l'ambre clair, 6,78:1 sur
    // l'ambre assombri du thème sombre.
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);

      const fill = await computed(page, "bg-brand");
      const ink = await computed(page, "text-primary-foreground");
      expect(
        contrast(fill.background, ink.color),
        `texte sur bouton de marque, thème ${theme}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  test("l'encre des remplissages de statut tient sur les trois, dans les deux thèmes", async ({
    page,
  }) => {
    // Le piège qu'a tendu le passage à un accent orange : `--on-accent` valait
    // du blanc en thème clair, et trois sites l'avaient posée sur un fond de
    // succès ou de danger — ça tenait par accident. L'encre d'accent est
    // désormais bleu nuit, et ces fonds-là ont leur propre jeton, `--on-status`.
    //
    // On lit les JETONS et non des utilitaires (`bg-success`, `text-on-status`) :
    // Tailwind ne génère que les classes qu'il trouve dans `src/`, et ce fichier
    // vit dans `e2e/`. Une classe absente ne fait pas échouer le test — elle le
    // rend muet, en laissant `computed()` mesurer la couleur héritée. Première
    // version de ce test : 3,80:1 mesurés sur une classe qui n'existait pas.
    // Ne pas « corriger » en ajoutant `e2e/` à `@source` : ça embarquerait des
    // classes de test dans le CSS livré.
    for (const theme of ["light", "dark"] as const) {
      const tokens = await readTokens(page, theme, [
        "--on-status",
        "--success",
        "--warning",
        "--danger",
      ]);
      for (const fill of ["--success", "--warning", "--danger"] as const) {
        expect(
          contrast(tokens[fill], tokens["--on-status"]),
          `${fill} + --on-status, thème ${theme}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  test("les trois signaux restent distinguables de la marque et entre eux", async ({ page }) => {
    // Le piège du choix d'un accent ambre : `--warning` était un or, à 6° de
    // teinte de la marque et à 1,15:1 en sombre. Sur l'échelle de score, la
    // barre « à travailler » et la barre « en progression » devenaient la même
    // couleur — une jauge qui ne dit plus rien. `--warning` est donc violet.
    //
    // Ce test mesure l'écart de TEINTE : deux remplissages voisins peuvent avoir
    // le même contraste avec le fond tout en étant indiscernables l'un de
    // l'autre, ce qu'un seuil de contraste ne verrait pas.
    for (const theme of ["light", "dark"] as const) {
      const t = await readTokens(page, theme, ["--accent", "--warning", "--danger", "--success"]);
      const pairs: [string, string][] = [
        ["--accent", "--warning"],
        ["--accent", "--danger"],
        ["--accent", "--success"],
        ["--warning", "--danger"],
        ["--warning", "--success"],
      ];
      for (const [a, b] of pairs) {
        // Discernable sur AU MOINS un des deux axes. Deux remplissages très
        // proches en teinte restent lisibles s'ils s'écartent franchement en
        // luminance (l'ambre et le rouge sombre du thème clair : 34° mais
        // 3,04:1 — de l'or vif contre un bordeaux). Ce qu'on interdit, c'est
        // qu'ils soient proches sur les DEUX, ce qui était le cas de l'ancien
        // `--warning` doré : 6° et 2,36:1.
        const gap = hueGap(t[a], t[b]);
        const ratio = contrast(t[a], t[b]);
        expect(
          gap > 40 || ratio > 2.5,
          `${a} (${t[a]}) et ${b} (${t[b]}) se ressemblent trop en thème ${theme} : ` +
            `${gap.toFixed(0)}° de teinte et ${ratio.toFixed(2)}:1`,
        ).toBe(true);
      }
    }
  });

  test("l'orange en TEXTE passe le seuil lisible dans les deux thèmes", async ({ page }) => {
    // `text-brand` (le remplissage) tombe à 2,68:1 sur fond clair : c'est
    // précisément pourquoi `--accent-ink` existe à côté. Sans ce test, le
    // premier `text-brand` réécrit à la main repasse sous le seuil sans bruit.
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);

      const surface = await computed(page, "bg-surface");
      const ink = await computed(page, "text-brand-ink");
      expect(
        contrast(surface.background, ink.color),
        `orange en texte sur une surface, thème ${theme}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
});
