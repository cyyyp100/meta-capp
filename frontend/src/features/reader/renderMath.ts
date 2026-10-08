import katex from "katex";
import "katex/dist/katex.min.css";

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Référence de page telle que Clikoda l'écrit (« p.29 », « p. 29 », « page 29 »,
// « pages 12 et 13 », « pp. 4-6 ») : chaque numéro devient un lien cliquable
// porteur de `data-page-ref`. Appliqué APRÈS l'échappement, sur du texte sûr —
// le seul HTML injecté est le nôtre.
const PAGE_REF_RE = /\b(pp?\.?\s?|pages?\s)(\d{1,4})((?:\s?(?:[-–,]|et|and|à|to)\s?\d{1,4})*)/gi;

export function linkPageRefs(escaped: string, maxPage?: number): string {
  const inRange = (n: number) => n >= 1 && (!maxPage || n <= maxPage);
  return escaped.replace(PAGE_REF_RE, (whole: string, prefix: string, first: string, rest: string) => {
    const link = (n: string) =>
      inRange(Number(n))
        ? `<a href="#" class="page-ref" data-page-ref="${n}" title="→ ${n}">${n}</a>`
        : n;
    if (!inRange(Number(first))) return whole;
    return prefix + link(first) + rest.replace(/\d{1,4}/g, link);
  });
}

/** Un morceau de texte : du texte, ou une formule en ligne ou en bloc. */
export interface MathSegment {
  kind: "text" | "inline" | "display";
  /** Le texte, ou le TeX de la formule sans ses délimiteurs. */
  value: string;
  /** Le morceau tel qu'écrit, délimiteurs compris (repli si KaTeX échoue). */
  raw: string;
}

/**
 * LE découpeur des formules, partagé par tout ce qui rend du texte de LLM ou
 * de carte (renderMathToHtml, anchorText.renderMarkedText). Une seule règle,
 * celle de pandoc :
 *   - `$$…$$` et `\[…\]` : formule en bloc, sur plusieurs lignes au besoin ;
 *   - `\(…\)` et `$…$` : formule en ligne, sur une ligne. Le `$` ouvrant est
 *     suivi d'un non-blanc, le `$` fermant précédé d'un non-blanc et pas suivi
 *     d'un chiffre — « 5$ et 10$ » ou « $20 ou $30 » restent du texte ;
 *   - `\$` et `\\` sont des caractères échappés, jamais des délimiteurs.
 * Un délimiteur sans fermeture reste du texte.
 */
export function splitMath(text: string): MathSegment[] {
  const segments: MathSegment[] = [];
  let buffer = "";
  const push = (kind: "inline" | "display", value: string, raw: string) => {
    if (buffer) segments.push({ kind: "text", value: buffer, raw: buffer });
    buffer = "";
    segments.push({ kind, value, raw });
  };
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    const next = text[i + 1];
    if (ch === "\\" && (next === "[" || next === "(")) {
      const close = next === "[" ? "\\]" : "\\)";
      const end = text.indexOf(close, i + 2);
      const body = end > i + 2 ? text.slice(i + 2, end) : "";
      if (body.trim() && (next === "[" || !body.includes("\n"))) {
        push(next === "[" ? "display" : "inline", body, text.slice(i, end + 2));
        i = end + 2;
        continue;
      }
    }
    if (ch === "\\" && next !== undefined) {
      buffer += ch + next; // \$, \\ : un caractère échappé
      i += 2;
      continue;
    }
    if (ch === "$" && next === "$") {
      const end = text.indexOf("$$", i + 2);
      if (end > i + 2 && text.slice(i + 2, end).trim()) {
        push("display", text.slice(i + 2, end), text.slice(i, end + 2));
        i = end + 2;
      } else {
        buffer += "$$";
        i += 2;
      }
      continue;
    }
    if (ch === "$") {
      const end = inlineMathEnd(text, i);
      if (end > 0) {
        push("inline", text.slice(i + 1, end), text.slice(i, end + 1));
        i = end + 1;
        continue;
      }
    }
    buffer += ch;
    i += 1;
  }
  if (buffer) segments.push({ kind: "text", value: buffer, raw: buffer });
  return segments;
}

/** Indice du `$` qui ferme la formule ouverte en `start`, ou -1 (règle pandoc). */
function inlineMathEnd(text: string, start: number): number {
  const first = text[start + 1];
  if (first === undefined || /\s/.test(first)) return -1;
  for (let j = start + 1; j < text.length; j++) {
    const c = text[j];
    if (c === "\n") return -1;
    if (c === "\\") {
      j += 1; // le caractère échappé n'est pas un délimiteur
      continue;
    }
    if (c === "$") {
      // Le premier `$` ferme ; s'il ne le peut pas (« $5 et $ ») il n'y a pas de formule.
      return !/\s/.test(text[j - 1]) && !/[0-9]/.test(text[j + 1] ?? "") ? j : -1;
    }
  }
  return -1;
}

/** Une formule en HTML KaTeX (trust=false : aucun lien ni attribut actif). */
export function renderTex(segment: MathSegment): string {
  try {
    return katex.renderToString(segment.value, { throwOnError: false, displayMode: segment.kind === "display" });
  } catch {
    return escapeHtml(segment.raw);
  }
}

// Rend le texte en HTML : les formules deviennent du KaTeX (`splitMath`), le
// reste est échappé (sécurité) avec les retours à la ligne conservés.
// `pageLinks` : rendre les références de page cliquables (réponses de Clikoda).
export function renderMathToHtml(text: string, opts?: { pageLinks?: boolean; maxPage?: number }): string {
  return splitMath(text)
    .map((segment) => {
      if (segment.kind !== "text") return renderTex(segment);
      const safe = escapeHtml(segment.value);
      return (opts?.pageLinks ? linkPageRefs(safe, opts.maxPage) : safe).replace(/\n/g, "<br/>");
    })
    .join("");
}
