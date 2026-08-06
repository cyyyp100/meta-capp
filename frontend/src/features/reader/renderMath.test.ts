// Verrou S6 : le rendu du texte LLM (seule entrée de dangerouslySetInnerHTML)
// ne doit JAMAIS laisser passer de HTML actif — le LLM local lit des PDFs
// arbitraires, son texte est une entrée non fiable.
import { describe, expect, it } from "vitest";

import { renderMathToHtml } from "./renderMath";

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
