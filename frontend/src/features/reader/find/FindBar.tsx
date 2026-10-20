// features/reader/find/FindBar.tsx — La barre de recherche du lecteur (Ctrl/Cmd+F).
//
// Dans la barre du haut, entre le titre et « Pause » : à gauche du dock de
// Clikoda, qu'elle ne recouvre jamais. Les gestes sont ceux d'un navigateur —
// Entrée / Maj+Entrée, ⌘/Ctrl+G et F3 (gérés par le lecteur), Échap pour
// fermer — et « 3 / 17 » est annoncé aux lecteurs d'écran.
import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import { useEffect, useRef } from "react";

import type { FindSummary } from "../../../api/types";
import { useT } from "../../../i18n";

interface Props {
  query: string;
  onQuery: (value: string) => void;
  summary: FindSummary | undefined;
  searching: boolean;
  /** Rang de l'occurrence courante (0-based), -1 sans résultat. */
  ordinal: number;
  /** L'occurrence courante est plus bas que la question bloquante : comptée, pas atteinte. */
  locked: boolean;
  onNext: () => void;
  onPrev: () => void;
  onClose: () => void;
  /** Change à chaque demande d'ouverture : le champ reprend le focus, texte sélectionné. */
  focusToken: number;
}

const iconBtn: React.CSSProperties = {
  display: "inline-grid",
  placeItems: "center",
  width: 26,
  height: 26,
  border: "none",
  borderRadius: "var(--radius-sm)",
  background: "transparent",
  color: "var(--text-soft)",
  cursor: "pointer",
};

export function FindBar({
  query,
  onQuery,
  summary,
  searching,
  ordinal,
  locked,
  onNext,
  onPrev,
  onClose,
  focusToken,
}: Props) {
  const t = useT();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [focusToken]);

  const total = summary?.total ?? 0;
  let status = "";
  if (query.trim()) {
    if (searching) status = t("reader.find_searching");
    else if (summary && !summary.too_short) {
      if (!summary.searchable) status = t("reader.find_no_text");
      else if (total === 0) status = t("reader.find_none");
      else status = t("reader.find_count", { cur: ordinal + 1, total });
    }
  }

  return (
    <div
      role="search"
      aria-label={t("reader.find_open")}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onClose();
        }
      }}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 2,
        minWidth: 0,
        padding: "2px 4px 2px 8px",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-sm)",
        background: "var(--surface)",
      }}
    >
      <Search className="size-3.5 shrink-0" aria-hidden style={{ color: "var(--muted)" }} />
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
          e.preventDefault();
          if (e.shiftKey) onPrev();
          else onNext();
        }}
        placeholder={t("reader.find_placeholder")}
        aria-label={t("reader.find_placeholder")}
        spellCheck={false}
        autoComplete="off"
        style={{
          width: 170,
          minWidth: 60,
          border: "none",
          outline: "none",
          background: "transparent",
          color: "var(--text)",
          fontSize: 13,
          padding: "4px 6px",
        }}
      />
      <span
        aria-live="polite"
        style={{
          fontSize: 12,
          color: locked ? "var(--warning)" : "var(--muted)",
          whiteSpace: "nowrap",
          fontVariantNumeric: "tabular-nums",
          padding: "0 4px",
        }}
      >
        {locked && status ? `${status} · ${t("reader.find_locked")}` : status}
      </span>
      <button
        type="button"
        style={{ ...iconBtn, opacity: total ? 1 : 0.4, cursor: total ? "pointer" : "default" }}
        onClick={onPrev}
        disabled={!total}
        aria-label={t("reader.find_prev")}
        title={t("reader.find_prev")}
      >
        <ChevronUp className="size-4" aria-hidden />
      </button>
      <button
        type="button"
        style={{ ...iconBtn, opacity: total ? 1 : 0.4, cursor: total ? "pointer" : "default" }}
        onClick={onNext}
        disabled={!total}
        aria-label={t("reader.find_next")}
        title={t("reader.find_next")}
      >
        <ChevronDown className="size-4" aria-hidden />
      </button>
      <button type="button" style={iconBtn} onClick={onClose} aria-label={t("reader.find_close")} title={t("reader.find_close")}>
        <X className="size-4" aria-hidden />
      </button>
    </div>
  );
}
