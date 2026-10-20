// features/reader/annotations/SelectionToolbar.tsx — La barre au-dessus d'une sélection.
//
// [+ Contexte] | les styles (surligné, souligné, barré, encadré) | les
// étiquettes — un clic surligne avec elle | [Note], qui surligne et ouvre la
// note. Le dernier style et la dernière étiquette sont retenus dans le
// navigateur, par simple commodité (`loadToolPrefs`).
//
// `onMouseDown preventDefault` : un clic dans la barre ne doit pas effacer la
// sélection qu'elle va consommer. `toolbarRef` permet au lecteur d'ignorer les
// mouseup qui viennent d'elle.
import { Highlighter, MessageSquarePlus, Plus, Square, Strikethrough, Underline } from "lucide-react";
import { motion } from "motion/react";
import type { Ref } from "react";

import type { AnnotationLabel, AnnotationStyle } from "../../../api/types";
import { useLangStore, useT } from "../../../i18n";
import { ANNOTATION_STYLES, colorVar, labelName } from "./palette";

const PREFS_KEY = "metacapp-annotation-tool";

/** Le dernier style et la dernière étiquette choisis — rien de grave s'ils manquent. */
export function loadToolPrefs(): { style: AnnotationStyle; labelId: number | null } {
  try {
    const raw = JSON.parse(localStorage.getItem(PREFS_KEY) ?? "null") as { style?: string; labelId?: number } | null;
    const style = ANNOTATION_STYLES.find((s) => s === raw?.style) ?? "highlight";
    return { style, labelId: typeof raw?.labelId === "number" ? raw.labelId : null };
  } catch {
    return { style: "highlight", labelId: null };
  }
}

export function saveToolPrefs(prefs: { style: AnnotationStyle; labelId: number | null }): void {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* stockage indisponible : la barre repartira des valeurs par défaut */
  }
}

export const STYLE_ICONS: Record<AnnotationStyle, typeof Highlighter> = {
  highlight: Highlighter,
  underline: Underline,
  strike: Strikethrough,
  outline: Square,
};

const button: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  border: "1px solid var(--border)",
  background: "var(--surface-soft)",
  color: "var(--text)",
  borderRadius: "var(--radius-sm)",
  padding: "5px 10px",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const iconButton: React.CSSProperties = { ...button, padding: 5 };

const separator = <span aria-hidden style={{ width: 1, alignSelf: "stretch", background: "var(--border)" }} />;

interface Props {
  x: number;
  y: number;
  /** Largeur du lecteur : la barre reste dans l'écran. */
  rootWidth: number;
  reduceMotion: boolean;
  toolbarRef: Ref<HTMLDivElement>;
  onContext: () => void;
  /** Absents (visite guidée) : la barre n'offre que le contexte. */
  annotate?: {
    labels: AnnotationLabel[];
    style: AnnotationStyle;
    labelId: number | null;
    onStyle: (style: AnnotationStyle) => void;
    onHighlight: (labelId: number) => void;
    onNote: () => void;
  };
}

export function SelectionToolbar({ x, y, rootWidth, reduceMotion, toolbarRef, onContext, annotate }: Props) {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const maxWidth = Math.min(560, rootWidth - 24);
  return (
    <motion.div
      ref={toolbarRef}
      role="toolbar"
      aria-label={t("annotations.toolbar")}
      initial={reduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduceMotion ? undefined : { opacity: 0, y: 4 }}
      transition={{ duration: 0.14, ease: [0.33, 1, 0.68, 1] }}
      style={{
        position: "absolute",
        left: Math.min(Math.max(x, maxWidth / 2 + 12), rootWidth - maxWidth / 2 - 12),
        top: Math.max(8, y - 44),
        // Le centrage passe par Motion (`x`) et non par `transform` : Motion
        // réécrit `transform` dès qu'il anime `y`, et la barre partait du
        // centre de la sélection au lieu d'y être centrée.
        x: "-50%",
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 6,
        maxWidth,
        padding: 4,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-lg)",
        zIndex: 60,
      }}
      onMouseDown={(e) => e.preventDefault()}
    >
      <button type="button" style={button} onClick={onContext}>
        <Plus className="size-3.5" aria-hidden />
        {t("reader.add_context")}
      </button>
      {annotate ? (
        <>
          {separator}
          {ANNOTATION_STYLES.map((style) => {
            const Icon = STYLE_ICONS[style];
            const active = annotate.style === style;
            return (
              <button
                key={style}
                type="button"
                aria-pressed={active}
                aria-label={t(`annotations.style.${style}`)}
                title={t(`annotations.style.${style}`)}
                onClick={() => annotate.onStyle(style)}
                style={{
                  ...iconButton,
                  background: active ? "var(--accent-soft)" : iconButton.background,
                  borderColor: active ? "var(--accent)" : "var(--border)",
                }}
              >
                <Icon className="size-3.5" aria-hidden />
              </button>
            );
          })}
          {separator}
          {annotate.labels.map((label) => {
            const name = labelName(label, lang);
            const last = annotate.labelId === label.id;
            return (
              <button
                key={label.id}
                type="button"
                data-label-swatch={label.id}
                aria-label={t("annotations.highlight_with", { label: name })}
                title={t("annotations.highlight_with", { label: name })}
                onClick={() => annotate.onHighlight(label.id)}
                style={{
                  width: 20,
                  height: 20,
                  padding: 0,
                  borderRadius: 999,
                  border: last ? "2px solid var(--text)" : "1px solid var(--border-strong)",
                  background: colorVar(label.color),
                  cursor: "pointer",
                }}
              />
            );
          })}
          {separator}
          <button type="button" style={button} onClick={annotate.onNote}>
            <MessageSquarePlus className="size-3.5" aria-hidden />
            {t("annotations.note_add")}
          </button>
        </>
      ) : null}
    </motion.div>
  );
}
