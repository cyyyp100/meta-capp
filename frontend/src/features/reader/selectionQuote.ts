import type { PageWord } from "../../api/types";
import { placedBoxes } from "./textLayer";

/**
 * Texte d'une sélection sur une page PDF, reconstruit depuis les mots du calque.
 *
 * Le calque de texte est fait de <span> posés mot à mot, sans espace entre
 * eux : `Selection.toString()` y lit « inatypicaltrainingscript… ». C'était le
 * texte des surlignages enregistrés et des extraits « + Contexte » envoyés à
 * Clikoda. On repart donc des mots sélectionnés (`data-wi`), dans l'ordre de la
 * page, joints par une espace — les mêmes mots que ceux dont les rects forment
 * le surlignage, si bien que la citation dit exactement ce qui s'est coloré.
 *
 * Césure : le moteur PDF termine le premier morceau d'un mot coupé en fin de
 * ligne par « - » (`_group_words`). Quand le mot suivant ouvre une autre bande
 * de ligne, on recolle les deux morceaux sans le tiret — « différen- » +
 * « tielles » → « différentielles », comme la recherche le lit. Entre lettres
 * seulement, à la manière de PDFium : « 2- » puis « 3 » reste « 2- 3 ». Les
 * marqueurs de césure bruts, s'il en reste, sont retirés.
 */

// Les mêmes que `utils/text.HYPHENATION_MARKERS` côté serveur.
const HYPHENATION_MARKERS = new Set(["￾", "\u0002", "­"]);
const withoutMarkers = (s: string) => [...s].filter((c) => !HYPHENATION_MARKERS.has(c)).join("");
const ENDS_WITH_BROKEN_WORD = /\p{L}-$/u;
const STARTS_WITH_LETTER = /^\p{L}/u;
// Deux mots d'une même bande ont le même `top` (placeWords) : la tolérance
// n'absorbe que l'arrondi.
const SAME_BAND_PT = 0.5;

export function buildQuote(
  words: PageWord[],
  selectedWi: Iterable<number>,
  boxes: Map<number, [number, number, number, number]> = placedBoxes(words),
): string {
  const order = [...new Set(selectedWi)].filter((wi) => words[wi] !== undefined).sort((a, b) => a - b);
  let out = "";
  let prev: { text: string; top: number } | null = null;
  for (const wi of order) {
    const text = withoutMarkers(words[wi][4]).trim();
    if (!text) continue;
    const top = boxes.get(wi)?.[1] ?? words[wi][1];
    if (prev) {
      const newLine = Math.abs(top - prev.top) > SAME_BAND_PT;
      if (newLine && ENDS_WITH_BROKEN_WORD.test(prev.text) && STARTS_WITH_LETTER.test(text)) {
        out = out.slice(0, -1);
      } else {
        out += " ";
      }
    }
    out += text;
    prev = { text, top };
  }
  return out;
}
