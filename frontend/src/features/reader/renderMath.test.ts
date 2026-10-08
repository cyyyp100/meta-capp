// Verrou S6 : le rendu du texte LLM (seule entrée de dangerouslySetInnerHTML)
// ne doit JAMAIS laisser passer de HTML actif — le LLM local lit des PDFs
// arbitraires, son texte est une entrée non fiable.
import { describe, expect, it } from "vitest";

import { renderMathToHtml, splitMath } from "./renderMath";

describe("renderMathToHtml — anti-XSS", () => {
  it("échappe le HTML hors formules", () => {
    const out = renderMathToHtml('<img src=x onerror="alert(1)"> & <script>alert(2)</script>');
    expect(out).not.toContain("<img");
    expect(out).not.toContain("<script");
    expect(out).toContain("&lt;img");
    expect(out).toContain("&amp;");
  });

  it("neutralise les payloads dans les formules KaTeX (trust=false)", () => {
    // \href est rendu comme TEXTE d'erreur (rouge) : le payload ne doit jamais
    // devenir un attribut href/gestionnaire — il ne survit qu'en texte inerte.
    const out = renderMathToHtml("$\\href{javascript:alert(1)}{clic}$");
    expect(out).not.toMatch(/href\s*=\s*["']?javascript:/i);
    expect(out).not.toContain("<a ");
    const out2 = renderMathToHtml("$\\htmlData{onmouseover=alert(1)}{x}$");
    expect(out2).not.toMatch(/<[^>]+\son\w+=/);
  });

  it("ne produit jamais de gestionnaire d'événement inline", () => {
    const hostile = 'texte " onmouseover=alert(1) $x " onclick=alert(2) $ fin';
    const out = renderMathToHtml(hostile);
    expect(out).not.toMatch(/<[^>]+\son\w+=/);
  });

  it("rend les formules valides et préserve les sauts de ligne", () => {
    const out = renderMathToHtml("Aire : $\\pi r^2$\nligne 2");
    expect(out).toContain("katex");
    expect(out).toContain("<br/>");
  });
});

describe("linkPageRefs", () => {
  it("rend p.29 / page 12 / pages 4-6 cliquables", () => {
    const html = renderMathToHtml("Voir Table I, p.29 et page 12, puis pages 4-6.", { pageLinks: true });
    expect(html).toContain('data-page-ref="29"');
    expect(html).toContain('data-page-ref="12"');
    expect(html).toContain('data-page-ref="4"');
    expect(html).toContain('data-page-ref="6"');
  });
  it("respecte la borne et ne touche pas au texte sans option", () => {
    expect(renderMathToHtml("cf. p.99", { pageLinks: true, maxPage: 10 })).not.toContain("data-page-ref");
    expect(renderMathToHtml("cf. p.9", { pageLinks: true, maxPage: 10 })).toContain('data-page-ref="9"');
    expect(renderMathToHtml("cf. p.9")).not.toContain("data-page-ref");
  });
});

describe("splitMath — une seule règle de découpage", () => {
  const kinds = (text: string) => splitMath(text).map((s) => [s.kind, s.value]);

  it("reconnaît $…$ et \\(…\\) en ligne", () => {
    expect(kinds("Soit $u_n$ et \\(v_n\\).")).toEqual([
      ["text", "Soit "],
      ["inline", "u_n"],
      ["text", " et "],
      ["inline", "v_n"],
      ["text", "."],
    ]);
  });

  it("reconnaît $$…$$ et \\[…\\] en bloc, sur plusieurs lignes", () => {
    expect(kinds("Aire :\n$$\n\\pi r^2\n$$\nfin")).toEqual([
      ["text", "Aire :\n"],
      ["display", "\n\\pi r^2\n"],
      ["text", "\nfin"],
    ]);
    expect(kinds("\\[\\frac{a}{b}\\]")).toEqual([["display", "\\frac{a}{b}"]]);
  });

  it("laisse la monnaie en texte (règle pandoc)", () => {
    for (const text of ["5$ et 10$", "Entre $20 et $30.", "$x$5", "un $ seul", "$ x$"]) {
      expect(splitMath(text).every((s) => s.kind === "text")).toBe(true);
    }
  });

  it("ne prend jamais un dollar échappé pour un délimiteur", () => {
    expect(splitMath("coûte \\$5 ou \\$6$").every((s) => s.kind === "text")).toBe(true);
    expect(kinds("$a \\$ b$")).toEqual([["inline", "a \\$ b"]]);
  });

  it("garde le texte d'un délimiteur sans fermeture", () => {
    expect(kinds("$$x et \\(y")).toEqual([["text", "$$x et \\(y"]]);
  });

  it("ne coupe pas une formule en ligne sur deux lignes", () => {
    expect(splitMath("$a\nb$").every((s) => s.kind === "text")).toBe(true);
  });
});

describe("renderMathToHtml — formules", () => {
  it("rend $$…$$ en bloc et \\(…\\) en ligne, sans dollar résiduel", () => {
    const html = renderMathToHtml("$$x^2$$ puis \\(y\\)");
    expect(html).toContain("katex-display");
    expect(html.match(/class="katex"/g)?.length).toBe(2);
    expect(html).not.toContain("$");
  });

  it("n'invente pas de formule entre deux montants", () => {
    const html = renderMathToHtml("5$ et 10$");
    expect(html).not.toContain("katex");
    expect(html).toBe("5$ et 10$");
  });
});
