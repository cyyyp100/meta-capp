// features/reader/annotations/AnnotationPopover.tsx — L'éditeur d'un élément cliqué sur la page.
//
// Ancrée sur un rectangle VIRTUEL, relu à chaque image (`updatePositionStrategy
// = "always"`) : la popover suit le défilement et le zoom. Le rectangle est
// l'union des éléments du DOM qui portent l'élément — les rects cliquables d'un
// surlignage PDF ou les <mark data-hl> d'un fichier de code (`data-hl`), le
// post-it ou le ruban d'un signet (`data-note`). Un fichier de code re-rend ses
// marques par innerHTML : on les relit donc à chaque fois, jamais une fois pour
// toutes.
import { useEffect, useLayoutEffect, useRef } from "react";

import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";

import { useT } from "../../../i18n";
import { AnnotationEditor } from "./AnnotationEditor";
import type { Annotations } from "./useAnnotations";

export interface EditingTarget {
  kind: "highlight" | "note";
  id: number;
  /** La note prend le focus (« Note » de la barre, post-it qu'on vient de poser). */
  focusNote?: boolean;
}

export function annotationSelector(kind: EditingTarget["kind"], id: number): string {
  return kind === "highlight" ? `[data-hl="${id}"]` : `[data-note="${id}"]`;
}

function unionRect(elements: Element[]): DOMRect | null {
  const rects = elements.map((el) => el.getBoundingClientRect()).filter((r) => r.width > 0 || r.height > 0);
  if (!rects.length) return null;
  const left = Math.min(...rects.map((r) => r.left));
  const top = Math.min(...rects.map((r) => r.top));
  const right = Math.max(...rects.map((r) => r.right));
  const bottom = Math.max(...rects.map((r) => r.bottom));
  return new DOMRect(left, top, right - left, bottom - top);
}

interface Props {
  target: EditingTarget | null;
  annotations: Annotations;
  onClose: () => void;
  onAddToContext: (page: number, quote: string) => void;
}

export function AnnotationPopover({ target, annotations, onClose, onAddToContext }: Props) {
  const t = useT();
  const targetRef = useRef(target);
  // Lu par la popover au moment de se placer, après le rendu.
  useLayoutEffect(() => {
    targetRef.current = target;
  });
  const lastRectRef = useRef<DOMRect>(new DOMRect(0, 0, 0, 0));
  const anchorRef = useRef({
    getBoundingClientRect: () => {
      const current = targetRef.current;
      if (current) {
        const rect = unionRect([...document.querySelectorAll(annotationSelector(current.kind, current.id))]);
        if (rect) lastRectRef.current = rect;
      }
      return lastRectRef.current;
    },
  });

  const highlight = target?.kind === "highlight" ? annotations.highlights.find((h) => h.id === target.id) : undefined;
  const note = target?.kind === "note" ? annotations.notes.find((n) => n.id === target.id) : undefined;
  const missing = target !== null && !highlight && !note;
  // Supprimé (ici, depuis le carnet, ou refusé par le serveur) : plus rien à éditer.
  useEffect(() => {
    if (missing) onClose();
  }, [missing, onClose]);

  return (
    <Popover open={Boolean(highlight || note)} onOpenChange={(open) => !open && onClose()}>
      <PopoverAnchor virtualRef={anchorRef} />
      <PopoverContent
        side="bottom"
        align="center"
        sideOffset={8}
        collisionPadding={12}
        updatePositionStrategy="always"
        aria-label={t(highlight ? "annotations.edit_highlight" : "annotations.edit_note")}
        className="w-80 p-3"
        // Clic sur un surlignage : rien ne prend le focus (on le lit d'abord) ;
        // « Note » ou post-it posé : le champ le prend lui-même (autoFocus).
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {highlight ? (
          <AnnotationEditor
            key={`h-${highlight.id}`}
            kind="highlight"
            item={highlight}
            labels={annotations.labels}
            readOnly={annotations.readOnly}
            autoFocus={target?.focusNote}
            onChange={(fields) => annotations.updateHighlight(highlight.id, fields)}
            onDelete={() => {
              annotations.deleteHighlight(highlight.id);
              onClose();
            }}
            onAddToContext={(quote) => {
              onAddToContext(highlight.page, quote);
              onClose();
            }}
          />
        ) : note ? (
          <AnnotationEditor
            key={`n-${note.id}`}
            kind="note"
            item={note}
            labels={annotations.labels}
            readOnly={annotations.readOnly}
            autoFocus={target?.focusNote}
            onChange={(fields) => annotations.updateNote(note.id, fields)}
            onDelete={() => {
              annotations.deleteNote(note.id);
              onClose();
            }}
          />
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
