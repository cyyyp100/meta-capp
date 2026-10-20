import { describe, expect, it } from "vitest";

import type { PageWord } from "../../api/types";
import { fitScaleX, layoutTextLayer, placeWords, placedBoxes, type LayerItem } from "./textLayer";

// Boîtes réelles de la page 1 d'un arXiv (points PDF, origine haut-gauche) :
// le tampon vertical de la marge gauche, puis trois mots d'une ligne du résumé.
const STAMP: PageWord = [18.1, 396.3, 32.3, 559.3, "arXiv:2410.13228v1"];
const LINE: PageWord[] = [
  [100, 158.9, 141.2, 167.2, "Nazanin"],
  [144, 157.2, 219.4, 169.5, "Daryakenarib,c,"],
  [221, 165.9, 222.3, 169.4, ","],
];

describe("placeWords", () => {
  it("reconnaît un tampon pivoté et lui garde sa boîte étroite", () => {
    const [stamp] = placeWords([STAMP]);
    expect(stamp.rotated).toBe(true);
    expect(stamp.width).toBeCloseTo(14.2, 1);
    expect(stamp.height).toBeCloseTo(163, 1);
  });

  it("n'agrège pas le tampon aux lignes qu'il traverse", () => {
    const placed = placeWords([STAMP, ...LINE]);
    const band = placed.filter((p) => !p.rotated);
    expect(band).toHaveLength(3);
    // La bande reste celle du texte courant : ~12 pt, pas les 163 pt du tampon.
    expect(band.every((p) => p.height < 15)).toBe(true);
  });

  it("aligne les mots d'une ligne sur une bande commune", () => {
    const placed = placeWords(LINE);
    const tops = new Set(placed.map((p) => p.top.toFixed(3)));
    const heights = new Set(placed.map((p) => p.height.toFixed(3)));
    expect(tops.size).toBe(1);
    expect(heights.size).toBe(1);
    // Bande médiane des deux mots de taille courante — la virgule, hors
    // gabarit, l'adopte au lieu de former une ligne de 3 pt pour elle seule.
    expect(placed[0].height).toBeCloseTo(10.3, 1);
    expect(placed[0].top + placed[0].height).toBeCloseTo(168.35, 2);
  });

  it("garde à chaque mot sa position et sa largeur horizontales", () => {
    const placed = placeWords(LINE);
    expect(placed.map((p) => p.left)).toEqual([100, 144, 221]);
    expect(placed[1].width).toBeCloseTo(75.4, 1);
  });

  it("ignore un glyphe démesuré dans le calcul de la bande", () => {
    // Une grande parenthèse de formule ne doit pas étirer la bande sur les
    // lignes voisines : la médiane l'écarte.
    const withBracket: PageWord[] = [...LINE, [230, 150, 234, 178, "("]];
    const placed = placeWords(withBracket);
    expect(placed.every((p) => p.height < 15)).toBe(true);
  });

  it("ne prend pas une ligature étroite pour du texte pivoté", () => {
    const narrow: PageWord[] = [[10, 100, 15.5, 107.3, "fi"], [20, 100, 27, 110, "The"]];
    expect(placeWords(narrow).every((p) => !p.rotated)).toBe(true);
  });
});

describe("placedBoxes", () => {
  it("indexe les boîtes finales par index de mot d'origine", () => {
    const boxes = placedBoxes([STAMP, ...LINE]);
    expect(boxes.size).toBe(4);
    expect(boxes.get(0)?.[3]).toBeCloseTo(559.3, 1); // le tampon, boîte inchangée
    const [x0, y0, x1, y1] = boxes.get(3)!; // la virgule, remontée sur la bande
    expect([x0, x1]).toEqual([221, 222.3]);
    expect(y1 - y0).toBeCloseTo(10.3, 1);
  });
});

describe("fitScaleX", () => {
  it("comprime le span à la largeur de sa boîte", () => {
    expect(fitScaleX("Nazanin", 8.3, 41.2, () => 50)).toBeCloseTo(0.824, 3);
  });

  it("reste neutre quand la mesure est indisponible", () => {
    expect(fitScaleX("Nazanin", 8.3, 41.2, () => 0)).toBe(1);
  });
});

describe("layoutTextLayer", () => {
  // Deux lignes de 10 pt, 2 pt d'interligne (boîtes au corps de la police).
  const PARA: PageWord[] = [
    [100, 100, 130, 110, "Les"],
    [134, 100, 170, 110, "portes"],
    [100, 112, 140, 122, "logiques"],
  ];
  const texts = (items: LayerItem[]) =>
    items.map((it) => (it.kind === "word" ? it.text : it.kind === "space" ? "␠" : "⏎"));

  it("met de vraies espaces entre les mots d'une ligne, et un saut entre deux lignes", () => {
    const items = layoutTextLayer(PARA);
    expect(texts(items)).toEqual(["Les", "␠", "portes", "⏎", "logiques"]);
    const space = items[1];
    // L'espace couvre exactement l'écart entre les deux mots.
    expect(space).toMatchObject({ kind: "space", left: 130, width: 4, top: 100, height: 10 });
  });

  it("suit l'ordre de lecture, pas l'ordre des bandes (deux colonnes)", () => {
    // Flux du PDF : la colonne de gauche, puis celle de droite. Les lignes 1
    // des deux colonnes tombent dans la même bande.
    const twoColumns: PageWord[] = [
      [50, 100, 80, 110, "gauche"],
      [84, 100, 110, 110, "un"],
      [50, 112, 90, 122, "gauche2"],
      [120, 100, 160, 110, "droite"],
      [120, 112, 160, 122, "droite2"],
    ];
    const items = layoutTextLayer(twoColumns);
    expect(texts(items)).toEqual(["gauche", "␠", "un", "⏎", "gauche2", "⏎", "droite", "⏎", "droite2"]);
    // Les marges des bouts de ligne s'arrêtent à mi-chemin de la gouttière.
    const un = items.find((it) => it.kind === "word" && it.text === "un");
    const droite = items.find((it) => it.kind === "word" && it.text === "droite");
    expect(un).toMatchObject({ padRight: 5 });
    expect(droite).toMatchObject({ padLeft: 5 });
    // Sans voisine, une marge de 1,5 ligne au plus.
    const droite2 = items.find((it) => it.kind === "word" && it.text === "droite2");
    expect(droite2).toMatchObject({ padRight: 15 });
  });

  it("étend la zone de saisie à la moitié de l'interligne, sans empiéter", () => {
    const items = layoutTextLayer(PARA).filter((it) => it.kind === "word");
    const [les, portes, logiques] = items;
    expect(les).toMatchObject({ padTop: 5, padBottom: 1 }); // rien au-dessus : une demi-ligne
    expect(portes).toMatchObject({ padTop: 5, padBottom: 1, padLeft: 0 });
    expect(logiques).toMatchObject({ padTop: 1, padBottom: 5 });
    // Le premier mot d'une ligne déborde dans la marge, le dernier aussi.
    expect(les).toMatchObject({ padLeft: 15, padRight: 0 });
    expect(portes).toMatchObject({ padRight: 15 });
  });

  it("retire du calque les mots cachés par un rappel libre", () => {
    const items = layoutTextLayer(PARA, [[132, 99, 172, 111]]);
    expect(texts(items)).toEqual(["Les", "⏎", "logiques"]);
  });

  it("garde un tampon pivoté à part, sans marge", () => {
    const items = layoutTextLayer([STAMP, ...PARA]);
    expect(items[0]).toMatchObject({ kind: "word", rotated: true, padLeft: 0, padTop: 0 });
    expect(items[1]).toEqual({ kind: "break" });
  });
});
