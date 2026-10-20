import type { PageWord } from "../../api/types";

/**
 * Géométrie du calque de texte transparent posé sur l'image d'une page.
 *
 * PDFium ne donne qu'une boîte englobante de glyphes par mot : sa hauteur est
 * celle des glyphes réellement présents (« use » ≈ hauteur d'x, « adaptive » va
 * du jambage haut au jambage bas, une virgule fait 3 pt), et sa largeur n'a
 * aucun rapport avec la largeur qu'aurait ce mot rendu dans la police du
 * navigateur. Poser les <span> tels quels — une taille de police par boîte,
 * largeur naturelle — donne exactement les deux bugs de sélection observés :
 *
 *  1. le texte pivoté explose. Le tampon arXiv du bord gauche est une boîte de
 *     14 × 163 pt ; interprétée comme du texte horizontal elle produit un span
 *     de ~140 pt de fonte étalé sur toute la largeur de la page, qui recouvre le
 *     résumé, capte le glisser de sélection et peint un énorme bloc bleu ;
 *  2. la bande de sélection est en dents de scie et dérive horizontalement,
 *     puisque chaque mot a sa propre hauteur et sa propre largeur naturelle.
 *
 * On corrige les deux ici, en points PDF (origine haut-gauche, comme partout
 * ailleurs dans l'app) : les mots horizontaux sont regroupés en lignes et
 * alignés sur une bande commune, les mots pivotés sont reconnus et gardent leur
 * boîte étroite. Le composant n'a plus qu'à mettre à l'échelle et à comprimer
 * chaque span à la largeur voulue (`fitScaleX`).
 */
export interface PlacedWord {
  /** Index dans le tableau de mots de la page (attribut `data-wi`). */
  wi: number;
  text: string;
  /** Boîte visée par le span, en points PDF. */
  left: number;
  top: number;
  width: number;
  height: number;
  /** Texte pivoté à 90° (tampon de marge) : la fonte se lit sur `width`. */
  rotated: boolean;
}

// Un mot d'au moins 3 caractères nettement plus haut que large est pivoté :
// horizontalement, trois glyphes font toujours plus large que haut. Le seuil
// laisse passer les mots courts d'un tampon vertical (« Oct » : ratio 2,0) sans
// jamais attraper une ligature étroite du texte courant (« fi » : ratio 1,3).
const ROTATED_MIN_CHARS = 3;
const ROTATED_MIN_RATIO = 1.6;

function isRotated(w: PageWord): boolean {
  return w[4].length >= ROTATED_MIN_CHARS && w[3] - w[1] > (w[2] - w[0]) * ROTATED_MIN_RATIO;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * Place les mots d'une page : bande commune par ligne pour le texte horizontal,
 * boîte d'origine pour le texte pivoté.
 *
 * Deux passes, parce qu'une ligne n'est pas une bande de hauteur constante :
 * une virgule est trois fois plus basse que les mots qui l'entourent et une
 * parenthèse de formule deux fois plus haute. On sème donc les lignes avec les
 * seuls mots de taille courante, on en tire une bande MÉDIANE (l'union
 * laisserait une intégrale étirer la ligne jusqu'à mordre sur ses voisines),
 * puis on y raccroche les glyphes hors gabarit. Ceux qui ne tombent dans aucune
 * bande — le gros titre d'une page de garde — forment leurs propres lignes.
 */
const SMALL_GLYPH = 0.6;
const TALL_GLYPH = 2;

interface Band {
  items: number[];
  top: number;
  height: number;
}

export function placeWords(words: PageWord[]): PlacedWord[] {
  const placed: PlacedWord[] = [];
  const horizontal: number[] = [];
  words.forEach((w, wi) => {
    if (isRotated(w)) {
      placed.push({ wi, text: w[4], left: w[0], top: w[1], width: w[2] - w[0], height: w[3] - w[1], rotated: true });
    } else {
      horizontal.push(wi);
    }
  });
  if (!horizontal.length) return placed;

  const heightOf = (wi: number) => words[wi][3] - words[wi][1];
  const centerOf = (wi: number) => (words[wi][1] + words[wi][3]) / 2;

  // Deux mots d'une même ligne se chevauchent largement : le centre de l'un
  // tombe dans la bande déjà couverte par l'autre. Le critère ne tient que sur
  // des boîtes de taille comparable — d'où le tri en amont.
  const seedLines = (indices: number[]): Band[] => {
    const lines: { items: number[]; span: [number, number] }[] = [];
    for (const wi of indices) {
      const center = centerOf(wi);
      const line = lines.find((ln) => center > ln.span[0] && center < ln.span[1]);
      if (line) {
        line.items.push(wi);
        line.span = [Math.min(line.span[0], words[wi][1]), Math.max(line.span[1], words[wi][3])];
      } else {
        lines.push({ items: [wi], span: [words[wi][1], words[wi][3]] });
      }
    }
    return lines.map((ln) => {
      const height = median(ln.items.map(heightOf));
      const bottom = median(ln.items.map((wi) => words[wi][3]));
      return { items: ln.items, top: bottom - height, height };
    });
  };

  const pageHeight = median(horizontal.map(heightOf));
  const regular = new Set(
    horizontal.filter((wi) => {
      const h = heightOf(wi);
      return h >= pageHeight * SMALL_GLYPH && h <= pageHeight * TALL_GLYPH;
    }),
  );
  const bands = seedLines([...regular]);

  const orphans: number[] = [];
  for (const wi of horizontal) {
    if (regular.has(wi)) continue;
    const center = centerOf(wi);
    let host = bands.find((b) => center >= b.top && center <= b.top + b.height);
    if (!host) {
      // Sinon : la bande que la boîte recoupe le plus (exposant, indice).
      let best = 0;
      for (const b of bands) {
        const overlap = Math.min(words[wi][3], b.top + b.height) - Math.max(words[wi][1], b.top);
        if (overlap > best) {
          best = overlap;
          host = b;
        }
      }
    }
    if (host) host.items.push(wi);
    else orphans.push(wi);
  }

  for (const band of [...bands, ...seedLines(orphans)]) {
    for (const wi of band.items) {
      const w = words[wi];
      placed.push({
        wi,
        text: w[4],
        left: w[0],
        top: band.top,
        width: w[2] - w[0],
        height: band.height,
        rotated: false,
      });
    }
  }
  return placed;
}

/** Boîtes finales indexées par `data-wi` — l'ancrage des surlignages enregistrés. */
export function placedBoxes(words: PageWord[]): Map<number, [number, number, number, number]> {
  const out = new Map<number, [number, number, number, number]>();
  for (const p of placeWords(words)) out.set(p.wi, [p.left, p.top, p.left + p.width, p.top + p.height]);
  return out;
}

/**
 * Élément du calque, dans l'ordre de LECTURE de la page (celui du flux du PDF).
 *
 * Les spans suivaient l'ordre des bandes : sur deux colonnes, la ligne 3 de
 * gauche et la ligne 3 de droite se suivaient dans le DOM, et sélectionner
 * trois lignes à gauche en colorait autant à droite. Et rien ne séparait deux
 * mots : la sélection avançait par à-coups, de mot en mot, et sautait au bout
 * de la page dès que le pointeur passait dans un vide.
 *
 * Désormais, comme dans le calque de PDF.js, une ligne est une suite de mots
 * séparés par de VRAIS espaces (un span par écart, qui le couvre), et deux
 * lignes par un saut (`<br>`) : la sélection est continue, la copie garde ses
 * espaces et ses retours. Chaque mot couvre exactement sa boîte (`width`,
 * `height`) ; autour, une zone de saisie (`pad*`) : la moitié de l'interligne
 * au-dessus et au-dessous, et un peu de marge avant le premier mot et après le
 * dernier — on attrape une ligne sans viser au pixel près, sans jamais
 * empiéter sur la voisine.
 */
export type LayerItem =
  | {
      kind: "word";
      wi: number;
      text: string;
      left: number;
      top: number;
      width: number;
      height: number;
      rotated: boolean;
      padTop: number;
      padBottom: number;
      padLeft: number;
      padRight: number;
    }
  | { kind: "space"; left: number; top: number; width: number; height: number; padTop: number; padBottom: number }
  | { kind: "break" };

// Deux mots d'une même bande ont le même `top` (placeWords) : la tolérance
// n'absorbe que l'arrondi.
export const SAME_BAND_PT = 0.5;
// Au-delà de cet écart (en hauteurs de ligne), deux mots consécutifs ne sont
// plus séparés par une espace : colonne voisine, cellule de tableau.
const WORD_GAP_MAX = 3;
// Zone de saisie, en hauteurs de ligne : au plus la moitié au-dessus et
// au-dessous (sinon la moitié de l'écart avec la ligne voisine), au plus 1,5
// avant le premier mot et après le dernier (sinon la moitié de l'écart avec le
// mot voisin de la même bande, dans l'autre colonne).
const LINE_REACH = 0.5;
const EDGE_REACH = 1.5;

interface Run {
  words: PlacedWord[];
  left: number;
  right: number;
  top: number;
  bottom: number;
}

function continuesRun(prev: PlacedWord, next: PlacedWord): boolean {
  if (prev.rotated || next.rotated) return false;
  if (Math.abs(prev.top - next.top) > SAME_BAND_PT || Math.abs(prev.height - next.height) > SAME_BAND_PT) return false;
  const gap = next.left - (prev.left + prev.width);
  return gap >= -prev.height * 0.5 && gap <= prev.height * WORD_GAP_MAX;
}

function intersects(p: PlacedWord, r: number[]): boolean {
  return p.left < r[2] && p.left + p.width > r[0] && p.top < r[3] && p.top + p.height > r[1];
}

/**
 * Le calque d'une page : ses mots, les espaces entre eux et les sauts de
 * ligne, dans l'ordre de lecture. `hidden` : boîtes (points PDF) dont les mots
 * sont retirés du calque — le passage caché d'un rappel libre ne doit pas se
 * sélectionner (ni se copier) sous son cache.
 */
export function layoutTextLayer(words: PageWord[], hidden: number[][] = []): LayerItem[] {
  const byWi = new Map(placeWords(words).map((p) => [p.wi, p]));
  const runs: Run[] = [];
  let current: PlacedWord[] = [];
  const close = () => {
    if (!current.length) return;
    const first = current[0];
    const last = current[current.length - 1];
    runs.push({ words: current, left: first.left, right: last.left + last.width, top: first.top, bottom: first.top + first.height });
    current = [];
  };
  for (let wi = 0; wi < words.length; wi++) {
    const p = byWi.get(wi);
    if (!p || hidden.some((r) => intersects(p, r))) {
      close();
      continue;
    }
    const prev = current[current.length - 1];
    if (!prev || !continuesRun(prev, p)) close();
    current.push(p);
  }
  close();

  const items: LayerItem[] = [];
  runs.forEach((run, ri) => {
    if (ri > 0) items.push({ kind: "break" });
    const [first] = run.words;
    if (first.rotated) {
      items.push({ kind: "word", ...first, padTop: 0, padBottom: 0, padLeft: 0, padRight: 0 });
      return;
    }
    const height = run.bottom - run.top;
    let above = -Infinity;
    let below = Infinity;
    let leftNeighbour = -Infinity;
    let rightNeighbour = Infinity;
    for (const other of runs) {
      if (other === run || other.words[0].rotated) continue;
      const overlapsX = other.left < run.right && other.right > run.left;
      if (overlapsX && other.bottom <= run.top + SAME_BAND_PT) above = Math.max(above, other.bottom);
      else if (overlapsX && other.top >= run.bottom - SAME_BAND_PT) below = Math.min(below, other.top);
      else if (Math.abs(other.top - run.top) <= SAME_BAND_PT && Math.abs(other.bottom - run.bottom) <= SAME_BAND_PT) {
        if (other.right <= run.left + SAME_BAND_PT) leftNeighbour = Math.max(leftNeighbour, other.right);
        else if (other.left >= run.right - SAME_BAND_PT) rightNeighbour = Math.min(rightNeighbour, other.left);
      }
    }
    const reach = (gap: number, cap: number) => Math.min(Math.max(gap / 2, 0), cap);
    const padTop = reach(run.top - above, height * LINE_REACH);
    const padBottom = reach(below - run.bottom, height * LINE_REACH);
    const padLeft = Math.min(reach(run.left - leftNeighbour, height * EDGE_REACH), Math.max(0, run.left));
    const padRight = reach(rightNeighbour - run.right, height * EDGE_REACH);
    run.words.forEach((p, k) => {
      const last = k === run.words.length - 1;
      items.push({
        kind: "word",
        ...p,
        top: run.top,
        height,
        padTop,
        padBottom,
        padLeft: k === 0 ? padLeft : 0,
        padRight: last ? padRight : 0,
      });
      if (last) return;
      const end = p.left + p.width;
      items.push({ kind: "space", left: end, top: run.top, width: run.words[k + 1].left - end, height, padTop, padBottom });
    });
  });
  return items;
}

/**
 * Facteur de compression horizontale d'un span pour qu'il couvre exactement sa
 * boîte (méthode du calque de texte de PDF.js). Le rapport est invariant à
 * l'échelle : on mesure une fois en points, il reste valable à tous les zooms.
 */
export function fitScaleX(text: string, fontSize: number, target: number, measure: Measure): number {
  const natural = measure(text, fontSize);
  if (!(natural > 0) || !(target > 0)) return 1;
  return target / natural;
}

export type Measure = (text: string, fontSize: number) => number;

/** Police du calque : la même chaîne côté <span> et côté mesure canvas. */
export const TEXT_LAYER_FONT = "sans-serif";

let ctx: CanvasRenderingContext2D | null | undefined;

/**
 * Largeur naturelle d'un texte, mesurée sur un canvas hors écran : pas de
 * lecture de layout, donc pas de reflow forcé sur les ~800 mots d'une page.
 * Renvoie 0 quand le canvas est indisponible (jsdom) → compression neutre.
 */
export const measureText: Measure = (text, fontSize) => {
  if (ctx === undefined) ctx = document.createElement("canvas").getContext("2d");
  if (!ctx?.measureText) return 0;
  ctx.font = `${fontSize}px ${TEXT_LAYER_FONT}`;
  return ctx.measureText(text).width;
};
