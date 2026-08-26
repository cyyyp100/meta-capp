import katex from "katex";

import type { ReaderBlock } from "../../api/types";

/**
 * Ancrage TEXTE sur pages reconstruites (édition cloud) : les citations de
 * Gemma et les surlignages mémorisés sont localisés par recherche « pliée »
 * (accents/casse/espaces normalisés) dans le texte des blocs — remplaçant de
 * `search_page` (PyMuPDF) qui n'a plus de sens sur un DOM reconstruit.
 *
 * `renderMarkedText` : même contrat de sécurité que renderMathToHtml (tout est
 * échappé, seuls les segments $...$ deviennent du KaTeX), plus l'injection de
 * <mark data-hl> autour des correspondances dans les segments NON-math.
 */

export interface TextMark {
  /** Texte à retrouver (citation LLM ou quote de surlignage). */
  text: string;
  /** Couleur CSS de fond. */
  color: string;
  /** Id de surlignage persisté (clic = suppression) — absent pour une citation. */
  id?: number;
  /**
   * Cache le passage au lieu de le surligner (rappel libre) : le texte devient
   * invisible mais garde sa place, donc la page ne se réagence pas sous les yeux.
   */
  masked?: boolean;
}

interface Folded {
  folded: string;
  /** map[i] = index dans la chaîne d'origine du caractère plié i. */
  map: number[];
}

/** Pliage : minuscules, accents retirés, suites d'espaces réduites à un espace. */
export function foldText(source: string): Folded {
  const folded: string[] = [];
  const map: number[] = [];
  let lastWasSpace = true; // avale aussi les espaces de tête
  for (let i = 0; i < source.length; i++) {
    const ch = source[i];
    if (/\s/.test(ch)) {
      if (!lastWasSpace) {
        folded.push(" ");
        map.push(i);
        lastWasSpace = true;
      }
      continue;
    }
    lastWasSpace = false;
    const base = ch.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    for (const b of base || ch.toLowerCase()) {
      folded.push(b);
      map.push(i);
    }
  }
  // Espace de queue éventuel.
  while (folded.length && folded[folded.length - 1] === " ") {
    folded.pop();
    map.pop();
  }
  return { folded: folded.join(""), map };
}

/** Localise `needle` dans `haystack` (plié) → [start, end) en indices ORIGINAUX. */
export function findFolded(haystack: string, needle: string): [number, number] | null {
  const h = foldText(haystack);
  const n = foldText(needle).folded;
  if (!n) return null;
  const at = h.folded.indexOf(n);
  if (at < 0) return null;
  const start = h.map[at];
  const lastFolded = at + n.length - 1;
  const end = h.map[lastFolded] + 1;
  return [start, end];
}

/** Blocs d'une page contenant `quote` (recherche pliée, bloc par bloc). */
export function findQuoteInBlocks(
  blocks: ReaderBlock[],
  quote: string,
): { blockId: string; start: number; end: number }[] {
  const hits: { blockId: string; start: number; end: number }[] = [];
  for (const block of blocks) {
    if (block.metadata?.reader_hidden) continue;
    const text = block.text ?? block.markdown ?? "";
    if (!text) continue;
    const span = findFolded(text, quote);
    if (span) hits.push({ blockId: block.id, start: span[0], end: span[1] });
  }
  return hits;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/**
 * Rend `text` (échappé + math $...$ en KaTeX) avec les `marks` surlignés dans
 * les segments non-math. Une correspondance qui chevauche une formule n'est
 * marquée que sur sa partie textuelle (limitation assumée).
 */
export function renderMarkedText(text: string, marks: TextMark[]): string {
  const parts = text.split(/(\$[^$\n]+\$)/g);
  return parts
    .map((part) => {
      if (part.length >= 2 && part.startsWith("$") && part.endsWith("$")) {
        try {
          return katex.renderToString(part.slice(1, -1), { throwOnError: false });
        } catch {
          return escapeHtml(part);
        }
      }
      return markSegment(part, marks);
    })
    .join("");
}

function markSegment(segment: string, marks: TextMark[]): string {
  // Intervalles [start, end) à marquer, fusionnés par priorité d'apparition.
  const spans: { start: number; end: number; mark: TextMark }[] = [];
  for (const mark of marks) {
    if (!mark.text.trim()) continue;
    const hit = findFolded(segment, mark.text);
    if (hit) spans.push({ start: hit[0], end: hit[1], mark });
  }
  if (!spans.length) return escapeHtml(segment).replace(/\n/g, "<br/>");
  spans.sort((a, b) => a.start - b.start || b.end - a.end);

  let html = "";
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) continue; // chevauchement : premier arrivé gagne
    html += escapeHtml(segment.slice(cursor, span.start)).replace(/\n/g, "<br/>");
    const idAttr = span.mark.id != null ? ` data-hl="${span.mark.id}"` : "";
    const cursorStyle = span.mark.id != null ? "cursor:pointer;" : "";
    // Masque : texte transparent et non sélectionnable — sinon un simple
    // glisser-copier le révélerait, et le rappel n'en serait plus un.
    const maskStyle = span.mark.masked
      ? "color:transparent;user-select:none;-webkit-user-select:none;"
      : "color:inherit;";
    html +=
      `<mark${idAttr} style="background:${span.mark.color};${cursorStyle}` +
      `border-radius:2px;padding:0 1px;${maskStyle}">` +
      escapeHtml(segment.slice(span.start, span.end)).replace(/\n/g, "<br/>") +
      "</mark>";
    cursor = span.end;
  }
  html += escapeHtml(segment.slice(cursor)).replace(/\n/g, "<br/>");
  return html;
}
