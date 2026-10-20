// features/reader/annotations/AnnotationEditor.tsx — Éditer un surlignage, un post-it ou un signet.
//
// Partagé par la popover de la page et par le carnet : l'étiquette, le style
// (surlignage seulement), la note — enregistrée d'elle-même, après une courte
// pause de frappe, et au départ de l'éditeur —, « Ajouter au contexte de
// Clikoda » et « Supprimer ». Ajouter au contexte compense ce que la page ne
// permet plus : un surlignage est cliquable, on ne peut plus y commencer une
// sélection.
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useConfirm } from "@/components/ui/confirm";

import { AutoGrowTextarea } from "../../../components/AutoGrowTextarea";
import type { AnnotationLabel, ReaderNote, SavedHighlight } from "../../../api/types";
import { useLangStore, useT } from "../../../i18n";
import { ANNOTATION_STYLES, colorVar, labelName } from "./palette";
import { STYLE_ICONS } from "./SelectionToolbar";
import { useStableCallback } from "../useStableCallback";
import type { HighlightFields, NoteFields } from "./useAnnotations";

/** Pause de frappe avant l'enregistrement de la note. */
const SAVE_DELAY_MS = 600;

type Props = {
  labels: AnnotationLabel[];
  readOnly?: boolean;
  /** Le champ de la note prend le focus (« Note » de la barre, post-it posé). */
  autoFocus?: boolean;
  onDelete: () => void;
  onAddToContext?: (quote: string) => void;
} & (
  | { kind: "highlight"; item: SavedHighlight; onChange: (fields: HighlightFields) => void }
  | { kind: "note"; item: ReaderNote; onChange: (fields: NoteFields) => void }
);

const smallButton: React.CSSProperties = {
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
};

export function AnnotationEditor(props: Props) {
  const { labels, readOnly = false, autoFocus = false, onDelete, onAddToContext } = props;
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const confirm = useConfirm();
  const saved = props.kind === "highlight" ? (props.item.note ?? "") : props.item.body;
  // L'éditeur suit UN élément : le parent le remonte (`key`) pour un autre.
  const [draft, setDraft] = useState(saved);
  // Le dernier texte envoyé : ni la réponse du serveur ni un second départ ne
  // renvoient ce qui est déjà parti.
  const sentRef = useRef(saved);

  const flush = useStableCallback(() => {
    if (readOnly || draft === sentRef.current) return;
    sentRef.current = draft;
    if (props.kind === "highlight") props.onChange({ note: draft.trim() ? draft : null });
    else props.onChange({ body: draft });
  });

  useEffect(() => {
    const timer = window.setTimeout(flush, SAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [draft, flush]);
  // Fermer la popover, replier l'élément du carnet : ce qui est tapé part quand même.
  useEffect(() => flush, [flush]);

  async function askDelete() {
    const ok = await confirm({
      title: t(props.kind === "highlight" ? "annotations.delete_confirm" : "annotations.delete_note_confirm"),
      confirmLabel: t("common.delete"),
      destructive: true,
    });
    if (ok) onDelete();
  }

  const labelId = props.item.label_id;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }} data-annotation-editor="">
      <div role="radiogroup" aria-label={t("annotations.label")} style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {labels.map((label) => {
          const name = labelName(label, lang);
          const checked = label.id === labelId;
          return (
            <button
              key={label.id}
              type="button"
              role="radio"
              aria-checked={checked}
              disabled={readOnly}
              title={name}
              onClick={() => {
                if (checked) return;
                if (props.kind === "highlight") props.onChange({ label_id: label.id });
                else props.onChange({ label_id: label.id });
              }}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "3px 8px 3px 4px",
                borderRadius: 999,
                fontSize: 12,
                border: checked ? "1.5px solid var(--text)" : "1px solid var(--border)",
                background: checked ? "var(--surface-soft)" : "var(--surface)",
                color: "var(--text)",
                cursor: readOnly ? "default" : "pointer",
              }}
            >
              <span aria-hidden style={{ width: 12, height: 12, borderRadius: 999, background: colorVar(label.color) }} />
              {name}
            </button>
          );
        })}
      </div>

      {props.kind === "highlight" ? (
        <div role="radiogroup" aria-label={t("annotations.style_label")} style={{ display: "flex", gap: 6 }}>
          {ANNOTATION_STYLES.map((style) => {
            const Icon = STYLE_ICONS[style];
            const checked = props.item.style === style;
            return (
              <button
                key={style}
                type="button"
                role="radio"
                aria-checked={checked}
                aria-label={t(`annotations.style.${style}`)}
                title={t(`annotations.style.${style}`)}
                disabled={readOnly}
                onClick={() => !checked && props.onChange({ style })}
                style={{
                  ...smallButton,
                  padding: 5,
                  background: checked ? "var(--accent-soft)" : smallButton.background,
                  borderColor: checked ? "var(--accent)" : "var(--border)",
                }}
              >
                <Icon className="size-3.5" aria-hidden />
              </button>
            );
          })}
        </div>
      ) : null}

      <AutoGrowTextarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={flush}
        readOnly={readOnly}
        autoFocus={autoFocus}
        maxHeight={220}
        aria-label={t(props.kind === "highlight" ? "annotations.note_label" : "annotations.body_label")}
        placeholder={t(props.kind === "highlight" ? "annotations.note_placeholder" : "annotations.body_placeholder")}
        style={{
          width: "100%",
          minHeight: 64,
          resize: "none",
          padding: "8px 10px",
          fontSize: 13,
          lineHeight: 1.5,
          fontFamily: "inherit",
          color: "var(--text)",
          background: "var(--surface-soft)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-sm)",
          boxSizing: "border-box",
        }}
      />

      <div style={{ display: "flex", gap: 6, justifyContent: "space-between", flexWrap: "wrap" }}>
        {props.kind === "highlight" && onAddToContext ? (
          <button type="button" style={smallButton} onClick={() => onAddToContext(props.item.quote)}>
            <Plus className="size-3.5" aria-hidden />
            {t("annotations.add_to_context")}
          </button>
        ) : (
          <span />
        )}
        {readOnly ? null : (
          <button type="button" style={{ ...smallButton, color: "var(--danger)" }} onClick={askDelete}>
            <Trash2 className="size-3.5" aria-hidden />
            {t("annotations.delete")}
          </button>
        )}
      </div>
    </div>
  );
}
