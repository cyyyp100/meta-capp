// Ancrage texte du lecteur reconstruit (M7) : recherche pliée + marquage sûr.
import { describe, expect, it } from "vitest";

import type { ReaderBlock } from "../../api/types";
import { findFolded, findQuoteInBlocks, foldText, renderMarkedText } from "./anchorText";

function block(id: string, text: string, hidden = false): ReaderBlock {
  return {
    id,
    type: "paragraph",
    page: 1,
    reading_order: 0,
    text,
    metadata: hidden ? { reader_hidden: true } : {},
  } as ReaderBlock;
}

describe("foldText / findFolded", () => {
  it("plie accents, casse et espaces multiples", () => {
    expect(foldText("  Élève   très  APPLIQUÉ ").folded).toBe("eleve tres applique");
  });

  it("retrouve une citation malgré accents et espacements différents", () => {
    const hay = "Le théorème central limite s'applique\nà toute somme de variables.";
    const hit = findFolded(hay, "theoreme central   LIMITE");
    expect(hit).not.toBeNull();
    const [start, end] = hit!;
    expect(hay.slice(start, end)).toBe("théorème central limite");
  });

  it("renvoie null quand la citation est absente", () => {
    expect(findFolded("un texte quelconque", "introuvable")).toBeNull();
  });
});

describe("findQuoteInBlocks", () => {
  it("localise le bloc porteur et ignore les blocs cachés", () => {
    const blocks = [
      block("p1_b000", "Introduction générale du chapitre."),
      block("p1_b001", "La self-attention pondère chaque token."),
      block("p1_b002", "La self-attention pondère chaque token.", true),
    ];
    const hits = findQuoteInBlocks(blocks, "self-attention pondère");
    expect(hits).toHaveLength(1);
    expect(hits[0].blockId).toBe("p1_b001");
  });
});

describe("renderMarkedText", () => {
  it("marque la correspondance et reste inerte (échappement)", () => {
    const out = renderMarkedText("Voir le théorème central limite ici.", [
      { text: "theoreme central limite", color: "yellow" },
    ]);
    expect(out).toContain("<mark");
    expect(out).toContain("théorème central limite</mark>");
  });

  it("un surlignage persisté porte data-hl (clic = suppression)", () => {
    const out = renderMarkedText("passage mémorisé par l'étudiant", [
      { text: "mémorisé", color: "gold", id: 42 },
    ]);
    expect(out).toContain('data-hl="42"');
  });

  it("ne casse pas les formules KaTeX et échappe le HTML hostile", () => {
    const out = renderMarkedText("Avec $x^2$ et <script>alert(1)</script> fin.", [
      { text: "fin", color: "cyan" },
    ]);
    expect(out).toContain("katex");
    expect(out).not.toContain("<script");
    expect(out).toContain("&lt;script&gt;");
    expect(out).toContain("<mark");
  });

  it("payload hostile DANS la marque : le texte marqué reste échappé", () => {
    const out = renderMarkedText("avant <b>gras</b> après", [
      { text: "<b>gras</b>", color: "pink" },
    ]);
    expect(out).not.toContain("<b>");
    expect(out).toContain("&lt;b&gt;");
  });
});
