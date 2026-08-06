import katex from "katex";
import "katex/dist/katex.min.css";

import type { ReaderBlock } from "../../../api/types";
import { renderMarkedText, type TextMark } from "../anchorText";
import { CodeBlock } from "./CodeBlock";

/**
 * Rendu d'UN bloc d'une page servie en blocs (fichiers de code), en React +
 * KaTeX.
 *
 * Sécurité : tout texte passe par `renderMarkedText` (échappement HTML strict,
 * seuls les segments $...$ deviennent du KaTeX ; les `marks` — citations de
 * Gemma, surlignages mémorisés — deviennent des <mark> inertes).
 */

const headingSizes: Record<number, string> = { 1: "1.5em", 2: "1.25em", 3: "1.1em" };

const NO_MARKS: TextMark[] = [];

export function BlockRenderer({
  block,
  marks = NO_MARKS,
}: {
  block: ReaderBlock;
  marks?: TextMark[];
}) {
  if (block.metadata?.reader_hidden) return null;

  switch (block.type) {
    case "heading": {
      const level = Math.min(3, Math.max(1, block.level ?? 1));
      const Tag = (["h2", "h3", "h4"] as const)[level - 1];
      return (
        <Tag
          style={{ fontSize: headingSizes[level], fontWeight: 700, margin: "1.1em 0 0.4em", lineHeight: 1.25 }}
          dangerouslySetInnerHTML={{ __html: renderMarkedText(block.text ?? "", marks) }}
        />
      );
    }

    case "formula":
      return (
        <div style={{ margin: "0.7em 0", overflowX: "auto", textAlign: "center" }}>
          <span
            dangerouslySetInnerHTML={{
              __html: katex.renderToString(block.latex ?? "", {
                displayMode: true,
                throwOnError: false,
              }),
            }}
          />
        </div>
      );

    case "figure":
      // Cette édition ne sert aucune image de bloc : seule la légende compte.
      return block.text ? <Caption text={block.text} marks={marks} /> : null;

    case "table":
      return <MarkdownTable markdown={block.markdown ?? ""} />;

    case "code":
      return (
        <CodeBlock
          code={block.text ?? ""}
          lang={typeof block.metadata?.lang === "string" ? block.metadata.lang : "text"}
          startLine={typeof block.metadata?.start_line === "number" ? block.metadata.start_line : 1}
          marks={marks}
        />
      );

    case "remark":
      return (
        <div
          style={{
            margin: "0.8em 0",
            padding: "10px 14px",
            borderLeft: "3px solid var(--accent)",
            background: "var(--surface-soft)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          }}
          dangerouslySetInnerHTML={{ __html: renderMarkedText(block.text ?? "", marks) }}
        />
      );

    default: {
      // paragraph (y compris légendes détectées)
      if (block.metadata?.is_caption) return <Caption text={block.text ?? ""} marks={marks} />;
      // Paragraphe coupé à la frontière de page (raccord OCR) : marges soudées.
      const continuesPrevious = Boolean(block.metadata?.continues_previous);
      const continuesNext = Boolean(block.metadata?.continues_next);
      return (
        <p
          style={{
            margin: `${continuesPrevious ? 0 : "0.55em"} 0 ${continuesNext ? 0 : "0.55em"}`,
            lineHeight: 1.65,
            textAlign: "justify",
          }}
          dangerouslySetInnerHTML={{ __html: renderMarkedText(block.text ?? "", marks) }}
        />
      );
    }
  }
}

function Caption({ text, marks = NO_MARKS }: { text: string; marks?: TextMark[] }) {
  return (
    <p
      style={{ margin: "0.4em 0 1em", fontSize: "0.85em", color: "var(--muted)", textAlign: "center" }}
      dangerouslySetInnerHTML={{ __html: renderMarkedText(text, marks) }}
    />
  );
}

/** Table markdown (lignes `| a | b |`) → <table>, cellules via renderMarkedText. */
function MarkdownTable({ markdown }: { markdown: string }) {
  const rows = markdown
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("|"))
    .map((line) => line.slice(1, line.endsWith("|") ? -1 : undefined).split("|").map((c) => c.trim()));
  // Ligne de séparation |---|:--| retirée.
  const body = rows.filter((cells) => !cells.every((c) => /^:?-{2,}:?$/.test(c)));
  if (!body.length) return null;
  const [head, ...rest] = body;
  const cellStyle: React.CSSProperties = {
    border: "1px solid var(--border)",
    padding: "4px 10px",
    fontSize: "0.9em",
  };
  return (
    <div style={{ overflowX: "auto", margin: "0.8em 0" }}>
      <table style={{ borderCollapse: "collapse", margin: "0 auto" }}>
        <thead>
          <tr>
            {head.map((cell, i) => (
              <th key={i} style={{ ...cellStyle, background: "var(--surface-soft)", fontWeight: 600 }}
                  dangerouslySetInnerHTML={{ __html: renderMarkedText(cell, NO_MARKS) }} />
            ))}
          </tr>
        </thead>
        <tbody>
          {rest.map((cells, ri) => (
            <tr key={ri}>
              {cells.map((cell, ci) => (
                <td key={ci} style={cellStyle} dangerouslySetInnerHTML={{ __html: renderMarkedText(cell, NO_MARKS) }} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
