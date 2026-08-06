// Lecteur reconstruit (édition cloud, M6) : routage des types de blocs,
// rôles cachés, et même verrou anti-XSS que renderMath (le contenu OCR vient
// d'un document arbitraire — entrée non fiable).
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ReaderBlock } from "../../../api/types";
import { BlockRenderer } from "./BlockRenderer";

function block(partial: Partial<ReaderBlock> & { type: ReaderBlock["type"] }): ReaderBlock {
  return {
    id: "p1_b000",
    page: 1,
    reading_order: 0,
    metadata: {},
    ...partial,
  } as ReaderBlock;
}

function html(b: ReaderBlock): string {
  return renderToStaticMarkup(<BlockRenderer block={b} />);
}

describe("BlockRenderer", () => {
  it("route chaque type vers sa forme (heading/formula/figure/table/remark/paragraph)", () => {
    expect(html(block({ type: "heading", text: "3.1 Attention", level: 2 }))).toContain("<h3");
    expect(html(block({ type: "heading", text: "Chapitre", level: 1 }))).toContain("<h2");

    const formula = html(block({ type: "formula", latex: "\\frac{a}{b}" }));
    expect(formula).toContain("katex");

    // Aucune image de bloc dans cette édition : seule la légende est rendue.
    const figure = html(block({ type: "figure", asset_name: "page_0001_img-0.png", text: "Figure 1" }));
    expect(figure).not.toContain("<img");
    expect(figure).toContain("Figure 1");

    const table = html(block({ type: "table", markdown: "| A | B |\n| :-- | :-- |\n| 1 | $x$ |" }));
    expect(table).toContain("<table");
    expect(table).toContain("<th");
    expect(table).not.toContain(":--"); // ligne de séparation retirée

    expect(html(block({ type: "remark", text: "À retenir" }))).toContain("border-left");
    expect(html(block({ type: "paragraph", text: "Du texte." }))).toContain("<p");
  });

  it("rend un bloc code : monospace, numéros de ligne, coloration légère", () => {
    const out = html(
      block({ type: "code", text: "def f():\n    return 1", metadata: { lang: "python", start_line: 10 } }),
    );
    expect(out).toContain("mc-code");
    // Gouttière de numéros de ligne (démarre à start_line, non sélectionnable).
    expect(out).toContain("10");
    expect(out).toContain("11");
    // Mots-clés colorés.
    expect(out).toContain("tok-k");
    expect(out).toContain("return");
  });

  it("masque les blocs reader_hidden (rôles header_footer/reference)", () => {
    expect(html(block({ type: "paragraph", text: "42", metadata: { reader_hidden: true } }))).toBe("");
  });

  it("rend le math inline des paragraphes via KaTeX", () => {
    const out = html(block({ type: "paragraph", text: "Soit $x^2$ un carré." }));
    expect(out).toContain("katex");
    expect(out).toContain("Soit ");
  });

  it("figure sans asset : la légende reste lisible, pas d'<img> cassée", () => {
    const out = html(block({ type: "figure", text: "Figure 2 : perdue" }));
    expect(out).not.toContain("<img");
    expect(out).toContain("Figure 2");
  });

  it("n'exécute JAMAIS le HTML venu de l'OCR (anti-XSS, verrou S6)", () => {
    const payload = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    for (const b of [
      block({ type: "paragraph", text: payload }),
      block({ type: "heading", text: payload, level: 1 }),
      block({ type: "table", markdown: `| ${payload} |\n| x |` }),
      block({ type: "remark", text: payload }),
      block({ type: "figure", asset_name: "page_0001_x.png", text: payload }),
      block({ type: "code", text: payload, metadata: { lang: "html", start_line: 1 } }),
    ]) {
      const out = html(b);
      // Les balises du payload doivent être ÉCHAPPÉES (texte inerte), jamais actives.
      expect(out).not.toContain("<script");
      expect(out).not.toContain("<img src=x");
      expect(out).toContain("&lt;");
    }
  });
});
