// features/reader/annotations/palette.ts — Couleurs et tracés de la prise de notes.
//
// La palette et les styles sont des vocabulaires FERMÉS, ceux de
// config/settings.py (ANNOTATION_COLORS, ANNOTATION_STYLES), que le serveur
// valide. Chaque couleur a son jeton `--note-<clé>` dans theme/tokens.css et
// son nom accessible `annotations.color.<clé>` dans les deux dictionnaires
// (tests/test_annotation_palette_tokens.py). Les jetons ne vivent que dans
// `:root` : un surlignage se pose sur une page de PDF, claire dans les deux
// thèmes.
import type { AnnotationColor, AnnotationLabel, AnnotationStyle } from "../../../api/types";
import { translate, type Lang } from "../../../i18n";

export const ANNOTATION_COLORS: readonly AnnotationColor[] = [
  "yellow",
  "orange",
  "red",
  "pink",
  "violet",
  "blue",
  "cyan",
  "green",
  "lime",
  "gray",
];

export const ANNOTATION_STYLES: readonly AnnotationStyle[] = ["highlight", "underline", "strike", "outline"];

/** Étiquette supprimée : le passage reste, dans cette couleur neutre. */
export const NEUTRAL_COLOR = "var(--note-none)";

export function colorVar(color: AnnotationColor): string {
  return `var(--note-${color})`;
}

/** Couleur d'un élément d'après son étiquette (neutre si elle a disparu). */
export function labelColor(label: AnnotationLabel | null | undefined): string {
  return label ? colorVar(label.color) : NEUTRAL_COLOR;
}

/** Nom affiché d'une étiquette : le sien, sinon celui du preset dans la langue
 *  de l'interface ; « Sans étiquette » pour un élément qui n'en a plus. */
export function labelName(label: AnnotationLabel | null | undefined, lang: Lang): string {
  if (!label) return translate(lang, "annotations.no_label");
  return label.name ?? translate(lang, `annotations.preset.${label.preset}`);
}

/** Rects SVG d'un surlignage d'une ligne, selon son style (points PDF). Le
 *  premier est le tracé visible ; la zone cliquable couvre toujours la ligne. */
export function svgStyle(
  style: AnnotationStyle,
  color: string,
  r: number[],
): { x: number; y: number; width: number; height: number; fill: string; fillOpacity: number; stroke?: string } {
  const [x0, y0, x1, y1] = r;
  const width = x1 - x0;
  const height = y1 - y0;
  const line = Math.max(0.9, Math.min(1.8, height * 0.12));
  switch (style) {
    case "underline":
      return { x: x0, y: y1 - line, width, height: line, fill: color, fillOpacity: 0.95 };
    case "strike":
      return { x: x0, y: y0 + height / 2 - line / 2, width, height: line, fill: color, fillOpacity: 0.95 };
    case "outline":
      return { x: x0 - 0.5, y: y0 - 0.5, width: width + 1, height: height + 1, fill: "none", fillOpacity: 0, stroke: color };
    default:
      return { x: x0, y: y0, width, height, fill: color, fillOpacity: 0.32 };
  }
}

/** Déclarations CSS d'un <mark> de fichier de code, selon son style. La
 *  couleur est une variable de la palette ; l'appelant l'échappe (escapeAttr). */
export function markCss(style: AnnotationStyle, color: string): string {
  switch (style) {
    case "underline":
      return `background:transparent;text-decoration:underline 2px ${color};text-underline-offset:3px;`;
    case "strike":
      return `background:transparent;text-decoration:line-through 2px ${color};`;
    case "outline":
      return `background:transparent;outline:1.5px solid ${color};outline-offset:1px;`;
    default:
      return `background:color-mix(in srgb, ${color} 40%, transparent);`;
  }
}
