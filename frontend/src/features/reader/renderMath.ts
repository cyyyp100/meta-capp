import katex from "katex";
import "katex/dist/katex.min.css";

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Rend le texte en HTML : les segments $...$ deviennent des formules KaTeX,
// le reste est échappé (sécurité) avec les retours à la ligne conservés.
export function renderMathToHtml(text: string): string {
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
      return escapeHtml(part).replace(/\n/g, "<br/>");
    })
    .join("");
}
