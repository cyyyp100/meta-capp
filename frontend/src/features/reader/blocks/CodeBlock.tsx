import { escapeAttr, findFolded, type TextMark } from "../anchorText";

/**
 * Rendu d'un bloc de CODE (document ouvert comme fichier source). Monospace,
 * numéros de ligne dans une gouttière NON sélectionnable (le texte copié /
 * ajouté au contexte reste le code pur), coloration syntaxique légère et
 * indépendante du langage, plus les `marks` du lecteur (surlignages mémorisés,
 * citations de Gemma).
 *
 * Sécurité : tout le code passe par `escape()` avant injection ; les seules
 * balises émises sont des <span class="tok-*"> et des <mark> inertes.
 */

const NO_MARKS: TextMark[] = [];

// Jeu de mots-clés volontairement transverse (plusieurs langages) : une légère
// sur-coloration d'un identifiant est préférable à un moteur par langage.
const KEYWORDS = new Set([
  "abstract", "and", "as", "assert", "async", "await", "begin", "bool", "boolean", "break", "byte",
  "case", "catch", "char", "class", "const", "constexpr", "continue", "debugger", "def", "default",
  "defer", "del", "delete", "do", "double", "elif", "else", "end", "enum", "except", "export",
  "extends", "extern", "false", "final", "finally", "float", "fn", "for", "from", "func", "function",
  "global", "go", "goto", "if", "impl", "implements", "import", "in", "include", "instanceof", "int",
  "interface", "is", "lambda", "let", "long", "match", "module", "mut", "namespace", "new", "nil",
  "none", "nonlocal", "not", "null", "or", "override", "package", "pass", "private", "protected",
  "pub", "public", "raise", "readonly", "record", "register", "return", "self", "short", "signed",
  "sizeof", "static", "std", "str", "string", "struct", "super", "switch", "template", "then", "this",
  "throw", "throws", "trait", "true", "try", "type", "typedef", "typeof", "undefined", "union",
  "unsigned", "use", "using", "var", "virtual", "void", "volatile", "when", "where", "while", "with",
  "yield",
]);

const HASH_LANGS = new Set([
  "python", "ruby", "bash", "powershell", "yaml", "toml", "ini", "r", "perl", "makefile",
  "dockerfile", "cmake", "terraform", "julia", "elixir", "coffeescript",
]);
const DASH_LANGS = new Set(["sql", "lua", "haskell"]);
const SLASH_LANGS = new Set([
  "c", "cpp", "csharp", "java", "kotlin", "swift", "go", "rust", "javascript", "typescript",
  "jsx", "tsx", "php", "scala", "dart", "objectivec", "groovy", "solidity", "protobuf", "less",
  "scss", "css", "vue", "svelte", "graphql", "fsharp",
]);

type CommentStyle = "hash" | "dash" | "slash" | "none";

function commentStyle(lang: string): CommentStyle {
  if (HASH_LANGS.has(lang)) return "hash";
  if (DASH_LANGS.has(lang)) return "dash";
  if (SLASH_LANGS.has(lang)) return "slash";
  return "none";
}

function escape(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function span(cls: string, text: string): string {
  return `<span class="${cls}">${escape(text)}</span>`;
}

function lineEnd(code: string, i: number): number {
  const nl = code.indexOf("\n", i);
  return nl === -1 ? code.length : nl;
}

const WORD = /[A-Za-z0-9_$]/;

/** Coloration syntaxique légère → HTML échappé (spans tok-*). */
function highlight(code: string, lang: string): string {
  const cs = commentStyle(lang);
  const blockComment = cs === "slash" || lang === "css" || lang === "scss" || lang === "less";
  const markup = lang === "html" || lang === "xml" || lang === "vue" || lang === "svelte";
  let out = "";
  let i = 0;
  const n = code.length;
  while (i < n) {
    const c = code[i];
    const two = code.slice(i, i + 2);
    if (blockComment && two === "/*") {
      const end = code.indexOf("*/", i + 2);
      const stop = end === -1 ? n : end + 2;
      out += span("tok-c", code.slice(i, stop));
      i = stop;
      continue;
    }
    if (markup && code.slice(i, i + 4) === "<!--") {
      const end = code.indexOf("-->", i + 4);
      const stop = end === -1 ? n : end + 3;
      out += span("tok-c", code.slice(i, stop));
      i = stop;
      continue;
    }
    if ((cs === "slash" && two === "//") || (cs === "dash" && two === "--") || (cs === "hash" && c === "#")) {
      const stop = lineEnd(code, i);
      out += span("tok-c", code.slice(i, stop));
      i = stop;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      let j = i + 1;
      while (j < n) {
        if (code[j] === "\\") {
          j += 2;
          continue;
        }
        if (code[j] === c) {
          j++;
          break;
        }
        if (code[j] === "\n" && c !== "`") break; // chaîne mono-ligne non fermée
        j++;
      }
      out += span("tok-s", code.slice(i, j));
      i = j;
      continue;
    }
    if (c >= "0" && c <= "9" && (i === 0 || !WORD.test(code[i - 1]))) {
      let j = i;
      while (j < n && /[0-9a-fA-FxXbBoO_.]/.test(code[j])) j++;
      out += span("tok-n", code.slice(i, j));
      i = j;
      continue;
    }
    if (/[A-Za-z_$]/.test(c)) {
      let j = i;
      while (j < n && WORD.test(code[j])) j++;
      const word = code.slice(i, j);
      out += KEYWORDS.has(word) ? span("tok-k", word) : escape(word);
      i = j;
      continue;
    }
    out += escape(c);
    i++;
  }
  return out;
}

/** Code coloré + surlignages : les segments marqués sont posés par-dessus la
 * coloration (recherche « pliée », comme le reste du lecteur reconstruit). */
function renderCode(code: string, lang: string, marks: TextMark[]): string {
  const spans: { start: number; end: number; mark: TextMark }[] = [];
  for (const mark of marks) {
    if (!mark.text.trim()) continue;
    const hit = findFolded(code, mark.text);
    if (hit) spans.push({ start: hit[0], end: hit[1], mark });
  }
  if (!spans.length) return highlight(code, lang);
  spans.sort((a, b) => a.start - b.start || b.end - a.end);
  let html = "";
  let cursor = 0;
  for (const s of spans) {
    if (s.start < cursor) continue; // chevauchement : premier arrivé gagne
    html += highlight(code.slice(cursor, s.start), lang);
    const idAttr = s.mark.id != null ? ` data-hl="${Number(s.mark.id)}"` : "";
    const cur = s.mark.id != null ? "cursor:pointer;" : "";
    html +=
      `<mark${idAttr} style="background:${escapeAttr(s.mark.color)};${cur}border-radius:2px;color:inherit">` +
      escape(code.slice(s.start, s.end)) +
      "</mark>";
    cursor = s.end;
  }
  html += highlight(code.slice(cursor), lang);
  return html;
}

export function CodeBlock({
  code,
  lang = "text",
  startLine = 1,
  marks = NO_MARKS,
}: {
  code: string;
  lang?: string;
  startLine?: number;
  marks?: TextMark[];
}) {
  const lineCount = code.length ? code.split("\n").length : 1;
  const gutter = Array.from({ length: lineCount }, (_, i) => startLine + i).join("\n");
  const preBase: React.CSSProperties = {
    margin: 0,
    fontFamily: "var(--font-mono)",
    fontSize: "0.82em",
    lineHeight: 1.6,
    tabSize: 4,
  };
  return (
    <div
      className="mc-code"
      style={{
        display: "flex",
        margin: "0.2em 0",
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border)",
        background: "var(--surface-soft)",
        overflow: "hidden",
      }}
    >
      <pre
        aria-hidden
        style={{
          ...preBase,
          flex: "0 0 auto",
          padding: "0.7em 0.5em 0.7em 0.9em",
          textAlign: "right",
          color: "var(--muted-light)",
          userSelect: "none",
          WebkitUserSelect: "none",
          borderRight: "1px solid var(--border)",
          background: "color-mix(in srgb, var(--surface) 60%, transparent)",
          whiteSpace: "pre",
        }}
      >
        {gutter}
      </pre>
      <pre
        style={{
          ...preBase,
          flex: "1 1 auto",
          padding: "0.7em 0.9em",
          color: "var(--text)",
          whiteSpace: "pre",
          overflowX: "auto",
          userSelect: "text",
          WebkitUserSelect: "text",
        }}
        dangerouslySetInnerHTML={{ __html: renderCode(code, lang, marks) }}
      />
    </div>
  );
}
