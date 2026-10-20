// features/reader/ReaderToolbar.tsx — La barre du haut du lecteur.
//
// Sortie de `Reader.tsx`, qui en dessinait chaque bouton en ligne : c'est ici
// que s'ajoutent les outils de lecture (la recherche, puis le carnet et les
// post-it), entre le titre et « Pause » — à gauche du dock de Clikoda, qu'ils
// ne recouvrent pas. `data-tour="toolbar"` reste l'ancre de la visite guidée.
import { Pause as PauseIcon } from "lucide-react";

import { useT } from "../../i18n";

const toolButton: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  color: "var(--text-soft)",
  fontWeight: 600,
  fontSize: 13,
  padding: "6px 12px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--surface)",
};

interface Props {
  title: string;
  onEnd: () => void;
  onPause: () => void;
  /** Pas de pause hors lecture (sas d'entrée, sas de sortie). */
  pauseDisabled: boolean;
  page: { current: number; total: number } | null;
  /** Les outils de lecture, entre le titre et « Pause ». */
  children?: React.ReactNode;
}

export function ReaderToolbar({ title, onEnd, onPause, pauseDisabled, page, children }: Props) {
  const t = useT();
  return (
    <div
      data-tour="toolbar"
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 18px",
        background: "color-mix(in srgb, var(--surface) 88%, transparent)",
        backdropFilter: "blur(8px)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <button onClick={onEnd} style={{ ...toolButton, cursor: "pointer" }}>
        {t("reader.end")}
      </button>
      <span style={{ fontWeight: 600, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
        {title}
      </span>
      {children}
      <button
        onClick={onPause}
        disabled={pauseDisabled}
        title={t("reader.pause_hint")}
        aria-label={t("reader.pause_hint")}
        style={{
          ...toolButton,
          cursor: pauseDisabled ? "default" : "pointer",
          opacity: pauseDisabled ? 0.5 : 1,
        }}
      >
        <PauseIcon className="size-3.5" aria-hidden />
        {t("reader.pause")}
      </button>
      {page && (
        <span style={{ color: "var(--muted)", fontSize: 13, whiteSpace: "nowrap" }}>
          {t("reader.page", { cur: page.current, total: page.total })}
        </span>
      )}
    </div>
  );
}

/** Bouton d'outil de la barre (ouvre la recherche, puis le carnet…). */
export function ToolbarIconButton({
  label,
  hint,
  disabled,
  pressed,
  onClick,
  children,
}: {
  label: string;
  hint?: string;
  disabled?: boolean;
  /** Bouton à bascule (carnet ouvert, pose d'un post-it en cours). */
  pressed?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={pressed}
      title={hint ?? label}
      style={{
        ...toolButton,
        padding: "6px 9px",
        ...(pressed ? { background: "var(--accent-soft)", borderColor: "var(--accent)", color: "var(--text)" } : {}),
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {children}
    </button>
  );
}
