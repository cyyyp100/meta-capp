// features/reader/annotations/PageNotesLayer.tsx — Post-it et signets d'une page.
//
// Un post-it de PDF est posé où l'élève a cliqué (points PDF × échelle), gardé
// dans la page ; un post-it de fichier de code, sans géométrie, s'empile dans
// la marge droite, sous le marque-page. Un signet est un ruban sur le bord
// GAUCHE de la page (le bord droit est celui de la dernière position), à la
// couleur de son étiquette. En z 7 : au-dessus du calque de texte et du cache
// du rappel libre (z 6), sous le marque-page (z 8). Un clic ouvre l'édition ;
// le texte se lit en infobulle.
import { StickyNote } from "lucide-react";

import type { AnnotationLabel, ReaderNote } from "../../../api/types";
import { useT } from "../../../i18n";
import { labelColor } from "./palette";

const STICKY_PX = 24;
const PREVIEW_CHARS = 160;

function preview(body: string): string {
  const flat = body.replace(/\s+/g, " ").trim();
  return flat.length > PREVIEW_CHARS ? `${flat.slice(0, PREVIEW_CHARS - 1)}…` : flat;
}

interface Props {
  notes: ReaderNote[];
  labelsById: Map<number, AnnotationLabel>;
  /** Pixels par point PDF ; null pour une page de code (pas de géométrie). */
  scale: number | null;
  /** Note que le carnet vient de désigner : elle clignote. */
  flashId: number | null;
  /** Absent : lecture seule (visite guidée). */
  onEdit?: (id: number) => void;
}

export function PageNotesLayer({ notes, labelsById, scale, flashId, onEdit }: Props) {
  const t = useT();
  if (!notes.length) return null;
  let stacked = 0;
  return (
    <>
      {notes.map((note) => {
        const color = labelColor(note.label_id !== null ? labelsById.get(note.label_id) : null);
        const flash = note.id === flashId ? { "data-flash": "" } : {};
        if (note.kind === "signet") {
          const title = note.body.trim() ? preview(note.body) : t("annotations.signet_title");
          return (
            <button
              key={note.id}
              type="button"
              data-note={note.id}
              {...flash}
              aria-label={t("annotations.signet_open", { title })}
              title={title}
              onClick={() => onEdit?.(note.id)}
              style={{
                position: "absolute",
                top: 24,
                left: 0,
                width: 10,
                height: 46,
                padding: 0,
                border: "none",
                borderRadius: "0 3px 3px 0",
                background: color,
                boxShadow: "var(--shadow-sm)",
                cursor: onEdit ? "pointer" : "default",
                zIndex: 7,
              }}
            />
          );
        }
        const positioned = scale !== null && note.x !== null && note.y !== null;
        const place: React.CSSProperties = positioned
          ? {
              left: `min(${(note.x as number) * (scale as number)}px, calc(100% - ${STICKY_PX + 2}px))`,
              top: `min(${(note.y as number) * (scale as number)}px, calc(100% - ${STICKY_PX + 2}px))`,
            }
          : { right: 10, top: 46 + stacked++ * (STICKY_PX + 6) };
        const title = note.body.trim() ? preview(note.body) : t("annotations.sticky_empty");
        return (
          <button
            key={note.id}
            type="button"
            data-note={note.id}
            {...flash}
            aria-label={t("annotations.sticky_open", { title })}
            title={title}
            onClick={() => onEdit?.(note.id)}
            style={{
              position: "absolute",
              ...place,
              display: "grid",
              placeItems: "center",
              width: STICKY_PX,
              height: STICKY_PX,
              padding: 0,
              border: "1px solid color-mix(in srgb, #000 18%, transparent)",
              borderRadius: 4,
              background: color,
              color: "#1d1f24",
              boxShadow: "var(--shadow-sm)",
              cursor: onEdit ? "pointer" : "default",
              zIndex: 7,
            }}
          >
            <StickyNote size={14} strokeWidth={2} aria-hidden />
          </button>
        );
      })}
    </>
  );
}
