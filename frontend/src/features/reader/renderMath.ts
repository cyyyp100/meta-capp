import katex from "katex";
import "katex/dist/katex.min.css";

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Référence de page telle que Gemma l'écrit (« p.29 », « p. 29 », « page 29 »,
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

// Rend le texte en HTML : les segments $...$ deviennent des formules KaTeX,
// le reste est échappé (sécurité) avec les retours à la ligne conservés.
// `pageLinks` : rendre les références de page cliquables (réponses de Gemma).
export function renderMathToHtml(text: string, opts?: { pageLinks?: boolean; maxPage?: number }): string {
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
      const safe = escapeHtml(part);
      return (opts?.pageLinks ? linkPageRefs(safe, opts.maxPage) : safe).replace(/\n/g, "<br/>");
    })
    .join("");
}
