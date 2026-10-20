import { describe, expect, it } from "vitest";

import type { PageWord } from "../../api/types";
import { buildQuote } from "./selectionQuote";

// Deux lignes d'un paragraphe (points PDF, origine haut-gauche), dont un mot
// coupé en fin de ligne tel que le moteur le découpe : « différen- » puis
// « tielles » au début de la suivante.
const WORDS: PageWord[] = [
  [72, 100, 98, 111, "Les"],
  [101, 100, 150, 111, "équations"],
  [153, 100, 212, 111, "différen-"],
  [72, 114, 110, 125, "tielles"],
  [113, 114, 140, 125, "sont"],
  [143, 114, 190, 125, "linéaires."],
];

describe("buildQuote", () => {
  it("joint les mots par des espaces, dans l'ordre de la page", () => {
    expect(buildQuote(WORDS, [2, 0, 1])).toBe("Les équations différen-");
  });

  it("recolle un mot coupé en fin de ligne, sans le tiret", () => {
    expect(buildQuote(WORDS, [0, 1, 2, 3, 4, 5])).toBe("Les équations différentielles sont linéaires.");
  });

  it("garde le tiret d'un mot composé sur une même ligne", () => {
    const words: PageWord[] = [
      [72, 100, 120, 111, "porte-"],
      [123, 100, 170, 111, "clés"],
    ];
    expect(buildQuote(words, [0, 1])).toBe("porte- clés");
  });

  it("ne recolle qu'entre deux lettres", () => {
    const words: PageWord[] = [
      [72, 100, 90, 111, "2-"],
      [72, 114, 80, 125, "3"],
    ];
    expect(buildQuote(words, [0, 1])).toBe("2- 3");
  });

  it("retire les marqueurs de césure bruts", () => {
    const words: PageWord[] = [[72, 100, 120, 111, "mot￾"]];
    expect(buildQuote(words, [0])).toBe("mot");
  });

  it("ignore les index inconnus et les doublons", () => {
    expect(buildQuote(WORDS, [4, 4, 99])).toBe("sont");
    expect(buildQuote(WORDS, [])).toBe("");
  });
});
