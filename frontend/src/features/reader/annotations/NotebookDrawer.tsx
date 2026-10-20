// features/reader/annotations/NotebookDrawer.tsx — Le carnet du document.
//
// Un tiroir à gauche. En tête, le marque-page et les signets (un signet de plus
// sur la page courante, avec son étiquette). Puis tout ce qui a été noté,
// groupé par page et rangé dans l'ordre de la page, filtrable (étiquettes,
// types, « avec note ») et cherchable — une recherche PLIÉE (accents, casse),
// qui ne fait que filtrer la liste. Un clic amène le lecteur sur l'élément, qui
// clignote ; « Modifier » l'édite sur place. Enfin l'export Markdown : un
// téléchargement, et « Copier », qui marche même sans téléchargement. L'ordre
// est celui du serveur (services/annotations : l'ordre de lecture), le même
// que celui de l'export : page par page, les surlignages, puis les post-it.
//
// Une note au-delà de la dernière page (le PDF a perdu des pages depuis) reste
// listée, grisée, sans « aller à ».
//
// Sa largeur s'ajuste par la poignée du bord droit (glisser, flèches au
// clavier, double-clic pour revenir au défaut). Elle est retenue dans le
// navigateur, comme celle de Clikoda : une commodité, rien de grave si elle
// se perd.
import { Bookmark, Check, ChevronDown, ChevronRight, ClipboardCopy, Download, Flag, StickyNote, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";

import { annotationsExportUrl, api } from "../../../api/client";
import { MathText } from "../../../components/MathText";
import type { AnnotationStyle, ReaderNote, SavedHighlight } from "../../../api/types";
import { useLangStore, useT } from "../../../i18n";
import { foldText } from "../anchorText";
import { AnnotationEditor } from "./AnnotationEditor";
import { LabelManager } from "./LabelManager";
import { labelColor, labelName } from "./palette";
import { STYLE_ICONS } from "./SelectionToolbar";
import type { Annotations } from "./useAnnotations";

/** Largeur par défaut du carnet (px), celle que le double-clic sur la poignée rend. */
export const NOTEBOOK_WIDTH = 340;
export const NOTEBOOK_MIN_WIDTH = 280;
const NOTEBOOK_MAX_WIDTH = 720;
// Ce que le carnet laisse toujours au document, quelle que soit la fenêtre.
const NOTEBOOK_KEEP_FOR_READING = 320;
const WIDTH_KEY = "metacapp-notebook-width";
const KEY_STEP = 16;
const KEY_STEP_FAST = 64;

/** La plus grande largeur permise dans une fenêtre de `viewport` px. */
export function maxNotebookWidth(viewport: number = window.innerWidth): number {
  return Math.max(NOTEBOOK_MIN_WIDTH, Math.min(NOTEBOOK_MAX_WIDTH, viewport - NOTEBOOK_KEEP_FOR_READING));
}

export function clampNotebookWidth(width: number, viewport: number = window.innerWidth): number {
  return Math.round(Math.min(Math.max(width, NOTEBOOK_MIN_WIDTH), maxNotebookWidth(viewport)));
}

/** La dernière largeur choisie, ramenée dans la fenêtre courante. */
export function loadNotebookWidth(): number {
  try {
    const saved = Number(localStorage.getItem(WIDTH_KEY));
    return clampNotebookWidth(Number.isFinite(saved) && saved > 0 ? saved : NOTEBOOK_WIDTH);
  } catch {
    return clampNotebookWidth(NOTEBOOK_WIDTH);
  }
}

export function saveNotebookWidth(width: number): void {
  try {
    localStorage.setItem(WIDTH_KEY, String(Math.round(width)));
  } catch {
    /* stockage indisponible : le carnet repartira de la largeur par défaut */
  }
}

export type NotebookTarget =
  | { kind: "highlight"; id: number; page: number }
  | { kind: "note"; id: number; page: number }
  | { kind: "page"; page: number };

type ItemType = "highlight" | "sticky" | "signet";
const ITEM_TYPES: ItemType[] = ["highlight", "sticky", "signet"];

type Item =
  | { type: "highlight"; key: string; page: number; label: number | null; text: string; note: string | null; highlight: SavedHighlight }
  | { type: "sticky" | "signet"; key: string; page: number; label: number | null; text: string; note: null; item: ReaderNote };

const chip = (active: boolean): React.CSSProperties => ({
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  padding: "3px 8px",
  borderRadius: 999,
  fontSize: 12,
  border: active ? "1.5px solid var(--text)" : "1px solid var(--border)",
  background: active ? "var(--surface-soft)" : "var(--surface)",
  color: "var(--text)",
  cursor: "pointer",
});

const footerButton: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 6,
  flex: 1,
  padding: "6px 10px",
  fontSize: 12.5,
  fontWeight: 600,
  color: "var(--text)",
  background: "var(--surface-soft)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
  cursor: "pointer",
  textDecoration: "none",
};

function clamp2(lines: number): React.CSSProperties {
  return { display: "-webkit-box", WebkitLineClamp: lines, WebkitBoxOrient: "vertical", overflow: "hidden" };
}

/**
 * La poignée du bord droit (motif « séparateur de fenêtre » : rôle
 * `separator`, valeur courante annoncée, flèches au clavier). Pendant un
 * glissé, une largeur par image au plus ; `done` dit que le geste est fini
 * (le lecteur retient alors la largeur).
 */
function ResizeHandle({ width, onResize }: { width: number; onResize: (width: number, done: boolean) => void }) {
  const t = useT();
  const dragRef = useRef<{ startX: number; startWidth: number; next: number; raf: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  // Pendant le glissé : curseur de redimensionnement partout, et aucune
  // sélection de texte du document sous le pointeur.
  useEffect(() => {
    if (!dragging) return;
    const { cursor, userSelect } = document.body.style;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.cursor = cursor;
      document.body.style.userSelect = userSelect;
    };
  }, [dragging]);
  useEffect(() => () => cancelAnimationFrame(dragRef.current?.raf ?? 0), []);

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { startX: e.clientX, startWidth: width, next: width, raf: 0 };
    setDragging(true);
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    drag.next = clampNotebookWidth(drag.startWidth + e.clientX - drag.startX);
    if (drag.raf) return;
    drag.raf = requestAnimationFrame(() => {
      drag.raf = 0;
      onResize(drag.next, false);
    });
  }

  function endDrag() {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    cancelAnimationFrame(drag.raf);
    setDragging(false);
    onResize(drag.next, true);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const step = e.shiftKey ? KEY_STEP_FAST : KEY_STEP;
    const next =
      e.key === "ArrowLeft"
        ? width - step
        : e.key === "ArrowRight"
          ? width + step
          : e.key === "Home"
            ? NOTEBOOK_MIN_WIDTH
            : e.key === "End"
              ? maxNotebookWidth()
              : null;
    if (next === null) return;
    e.preventDefault();
    onResize(clampNotebookWidth(next), true);
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t("reader.notebook_resize")}
      aria-valuenow={width}
      aria-valuemin={NOTEBOOK_MIN_WIDTH}
      aria-valuemax={maxNotebookWidth()}
      title={t("reader.notebook_resize_hint")}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onLostPointerCapture={endDrag}
      onDoubleClick={() => onResize(clampNotebookWidth(NOTEBOOK_WIDTH), true)}
      onKeyDown={onKeyDown}
      className="group absolute inset-y-0 -right-1.5 z-10 w-3 cursor-col-resize touch-none focus-visible:outline-none"
    >
      <span
        aria-hidden
        className={cn(
          "absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 transition-colors duration-fast ease-brand",
          "group-hover:bg-[var(--accent)] group-focus-visible:bg-[var(--accent)]",
          dragging ? "bg-[var(--accent)]" : "bg-transparent",
        )}
      />
    </div>
  );
}

interface Props {
  docId: number;
  pageCount: number;
  currentPage: number;
  bookmark: number | null;
  annotations: Annotations;
  /** Largeur du carnet (px), tenue par le lecteur. */
  width: number;
  /** Nouvelle largeur demandée par la poignée ; `done` : fin du geste. */
  onResize: (width: number, done: boolean) => void;
  onClose: () => void;
  onGoTo: (target: NotebookTarget) => void;
  onAddToContext: (page: number, quote: string) => void;
}

export function NotebookDrawer({
  docId,
  pageCount,
  currentPage,
  bookmark,
  annotations,
  width,
  onResize,
  onClose,
  onGoTo,
  onAddToContext,
}: Props) {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const { labels, labelsById, readOnly } = annotations;
  const [labelFilter, setLabelFilter] = useState<Set<number>>(() => new Set());
  const [typeFilter, setTypeFilter] = useState<Set<ItemType>>(() => new Set());
  const [withNote, setWithNote] = useState(false);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [labelsOpen, setLabelsOpen] = useState(false);
  const [signetLabel, setSignetLabel] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  // Dans l'ordre du serveur : les surlignages, puis les post-it et signets.
  const items = useMemo<Item[]>(
    () => [
      ...annotations.highlights.map((h): Item => ({
        type: "highlight",
        key: `h-${h.id}`,
        page: h.page,
        label: h.label_id,
        text: h.quote,
        note: h.note,
        highlight: h,
      })),
      ...annotations.notes.map((n): Item => ({ type: n.kind, key: `n-${n.id}`, page: n.page, label: n.label_id, text: n.body, note: null, item: n })),
    ],
    [annotations.highlights, annotations.notes],
  );

  const folded = foldText(query).folded;
  const visible = items.filter((item) => {
    if (labelFilter.size && (item.label === null || !labelFilter.has(item.label))) return false;
    if (typeFilter.size && !typeFilter.has(item.type)) return false;
    if (withNote && !(item.type === "highlight" ? item.note : item.text.trim())) return false;
    if (folded && !foldText(`${item.text} ${item.note ?? ""}`).folded.includes(folded)) return false;
    return true;
  });
  const signets = visible.filter((item) => item.type === "signet");
  const byPage = new Map<number, Item[]>();
  for (const item of visible) {
    if (item.type === "signet") continue;
    byPage.set(item.page, [...(byPage.get(item.page) ?? []), item]);
  }

  function toggle<T>(set: Set<T>, value: T, apply: (next: Set<T>) => void) {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    apply(next);
  }

  async function copyMarkdown() {
    try {
      await navigator.clipboard.writeText(await api.annotationsMarkdown(docId));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      toast.error(t("reader.notebook_copy_error"));
    }
  }

  function goTo(item: Item) {
    if (item.page > pageCount) return;
    if (item.type === "highlight") onGoTo({ kind: "highlight", id: item.highlight.id, page: item.page });
    else onGoTo({ kind: "note", id: item.item.id, page: item.page });
  }

  function itemRow(item: Item) {
    const beyond = item.page > pageCount;
    const label = item.label !== null ? labelsById.get(item.label) : null;
    const open = editing === item.key;
    const Icon =
      item.type === "highlight" ? STYLE_ICONS[item.highlight.style as AnnotationStyle] : item.type === "signet" ? Flag : StickyNote;
    return (
      <li key={item.key} style={{ borderBottom: "1px solid var(--border)", opacity: beyond ? 0.5 : 1 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 2px" }}>
          <span
            aria-hidden
            style={{
              display: "grid",
              placeItems: "center",
              flex: "0 0 auto",
              width: 22,
              height: 22,
              marginTop: 1,
              borderRadius: 6,
              background: labelColor(label),
              color: "#1d1f24",
            }}
          >
            <Icon className="size-3" />
          </span>
          <button
            type="button"
            disabled={beyond}
            title={beyond ? t("reader.notebook_beyond_end") : t("reader.notebook_goto")}
            onClick={() => goTo(item)}
            style={{
              flex: 1,
              minWidth: 0,
              textAlign: "left",
              padding: 0,
              border: "none",
              background: "transparent",
              color: "var(--text)",
              cursor: beyond ? "default" : "pointer",
              fontSize: 13,
              lineHeight: 1.45,
            }}
          >
            <span style={{ display: "block", fontSize: 11.5, color: "var(--muted)" }}>{labelName(label, lang)}</span>
            <span style={{ ...clamp2(3), fontStyle: item.type === "highlight" ? "normal" : "italic" }}>
              {item.text.trim() || t("annotations.sticky_empty")}
            </span>
            {item.note ? (
              // Les formules $…$ de la note rendues, comme dans la carte au survol.
              <MathText text={item.note} style={{ ...clamp2(2), marginTop: 3, color: "var(--text-soft)", fontSize: 12.5 }} />
            ) : null}
          </button>
          {readOnly ? null : (
            <button
              type="button"
              aria-expanded={open}
              aria-label={t("reader.notebook_edit")}
              title={t("reader.notebook_edit")}
              onClick={() => setEditing(open ? null : item.key)}
              style={{
                flex: "0 0 auto",
                display: "grid",
                placeItems: "center",
                width: 24,
                height: 24,
                padding: 0,
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                background: "var(--surface)",
                color: "var(--text-soft)",
                cursor: "pointer",
              }}
            >
              {open ? <ChevronDown className="size-3.5" aria-hidden /> : <ChevronRight className="size-3.5" aria-hidden />}
            </button>
          )}
        </div>
        {open ? (
          <div style={{ padding: "0 2px 10px" }}>
            {item.type === "highlight" ? (
              <AnnotationEditor
                key={item.key}
                kind="highlight"
                item={item.highlight}
                labels={labels}
                onChange={(fields) => annotations.updateHighlight(item.highlight.id, fields)}
                onDelete={() => annotations.deleteHighlight(item.highlight.id)}
                onAddToContext={(quote) => onAddToContext(item.page, quote)}
              />
            ) : (
              <AnnotationEditor
                key={item.key}
                kind="note"
                item={item.item}
                labels={labels}
                onChange={(fields) => annotations.updateNote(item.item.id, fields)}
                onDelete={() => annotations.deleteNote(item.item.id)}
              />
            )}
          </div>
        ) : null}
      </li>
    );
  }

  const chosenSignetLabel = signetLabel ?? labels[0]?.id ?? null;
  const pages = [...byPage.keys()].sort((a, b) => a - b);
  return (
    <aside
      aria-label={t("reader.notebook_title")}
      style={{
        position: "absolute",
        top: 56,
        left: 0,
        bottom: 0,
        width,
        maxWidth: "calc(100% - 24px)",
        display: "flex",
        flexDirection: "column",
        background: "var(--surface)",
        borderRight: "1px solid var(--border)",
        boxShadow: "var(--shadow-lg)",
        zIndex: 45,
      }}
    >
      <ResizeHandle width={width} onResize={onResize} />
      <header style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 14px 8px" }}>
        <h2 style={{ margin: 0, flex: 1, fontSize: 15, fontWeight: 700 }}>{t("reader.notebook_title")}</h2>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>{t("reader.notebook_count", { n: items.length })}</span>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("reader.notebook_close")}
          style={{ display: "grid", placeItems: "center", width: 28, height: 28, padding: 0, border: "none", background: "transparent", color: "var(--text-soft)", cursor: "pointer" }}
        >
          <X className="size-4" aria-hidden />
        </button>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: "0 14px 12px" }}>
        {/* Repères : le marque-page, puis les signets. */}
        <section aria-label={t("reader.notebook_marks")} style={{ display: "flex", flexDirection: "column", gap: 6, paddingBottom: 10 }}>
          {bookmark !== null ? (
            <button type="button" onClick={() => onGoTo({ kind: "page", page: bookmark })} style={{ ...chip(false), alignSelf: "flex-start" }}>
              <Bookmark className="size-3.5" aria-hidden style={{ color: "var(--accent)" }} />
              {t("resume.bookmark", { page: bookmark })}
            </button>
          ) : null}
          {signets.length ? <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>{signets.map(itemRow)}</ul> : null}
          {readOnly ? null : (
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <button
                type="button"
                style={chip(false)}
                onClick={() =>
                  void annotations.createNote({ kind: "signet", page: currentPage, labelId: chosenSignetLabel })
                }
              >
                <span aria-hidden style={{ width: 4, height: 14, borderRadius: 2, background: labelColor(chosenSignetLabel !== null ? labelsById.get(chosenSignetLabel) : null) }} />
                {t("annotations.signet_add", { page: currentPage })}
              </button>
              <select
                aria-label={t("annotations.signet_label")}
                value={chosenSignetLabel ?? ""}
                onChange={(e) => setSignetLabel(Number(e.target.value))}
                style={{ fontSize: 12, padding: "3px 6px", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", background: "var(--surface)", color: "var(--text)" }}
              >
                {labels.map((label) => (
                  <option key={label.id} value={label.id}>
                    {labelName(label, lang)}
                  </option>
                ))}
              </select>
            </div>
          )}
        </section>

        {/* Filtres et recherche. */}
        <section aria-label={t("reader.notebook_filters")} style={{ display: "flex", flexDirection: "column", gap: 8, padding: "10px 0", borderTop: "1px solid var(--border)" }}>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("reader.notebook_search")}
            aria-label={t("reader.notebook_search")}
            style={{ padding: "6px 10px", fontSize: 13, color: "var(--text)", background: "var(--surface-soft)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}
          />
          <div role="group" aria-label={t("reader.notebook_filter_labels")} style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {labels.map((label) => (
              <button
                key={label.id}
                type="button"
                aria-pressed={labelFilter.has(label.id)}
                onClick={() => toggle(labelFilter, label.id, setLabelFilter)}
                style={chip(labelFilter.has(label.id))}
              >
                <span aria-hidden style={{ width: 10, height: 10, borderRadius: 999, background: labelColor(label) }} />
                {labelName(label, lang)}
              </button>
            ))}
          </div>
          <div role="group" aria-label={t("reader.notebook_filter_types")} style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {ITEM_TYPES.map((type) => (
              <button key={type} type="button" aria-pressed={typeFilter.has(type)} onClick={() => toggle(typeFilter, type, setTypeFilter)} style={chip(typeFilter.has(type))}>
                {t(`reader.notebook_type_${type}`)}
              </button>
            ))}
            <button type="button" aria-pressed={withNote} onClick={() => setWithNote((on) => !on)} style={chip(withNote)}>
              {t("reader.notebook_with_note")}
            </button>
          </div>
        </section>

        {/* Tout ce qui est noté, page par page. */}
        {pages.length ? (
          pages.map((page) => (
            <section key={page} aria-label={t("annotations.page", { page })}>
              <h3 style={{ margin: "12px 0 2px", fontSize: 12, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                {t("annotations.page", { page })}
              </h3>
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>{(byPage.get(page) ?? []).map(itemRow)}</ul>
            </section>
          ))
        ) : (
          <p style={{ color: "var(--muted)", fontSize: 13 }}>
            {items.length ? t("reader.notebook_no_results") : t("reader.notebook_empty")}
          </p>
        )}

        {/* Les étiquettes : renommer, recolorer, ajouter, supprimer, ranger. */}
        {readOnly ? null : (
          <section style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
            <button
              type="button"
              aria-expanded={labelsOpen}
              onClick={() => setLabelsOpen((open) => !open)}
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 0", border: "none", background: "transparent", color: "var(--text)", fontWeight: 600, fontSize: 13, cursor: "pointer" }}
            >
              {labelsOpen ? <ChevronDown className="size-3.5" aria-hidden /> : <ChevronRight className="size-3.5" aria-hidden />}
              {t("annotations.labels_title")}
            </button>
            {labelsOpen ? <LabelManager annotations={annotations} /> : null}
          </section>
        )}
      </div>

      <footer style={{ display: "flex", gap: 8, padding: "10px 14px", borderTop: "1px solid var(--border)" }}>
        <a href={annotationsExportUrl(docId)} download style={footerButton}>
          <Download className="size-3.5" aria-hidden />
          {t("reader.notebook_export")}
        </a>
        <button
          type="button"
          onClick={() => void copyMarkdown()}
          aria-label={copied ? t("reader.notebook_copied") : t("reader.notebook_copy")}
          title={t("reader.notebook_copy")}
          style={footerButton}
        >
          {copied ? <Check className="size-3.5" aria-hidden /> : <ClipboardCopy className="size-3.5" aria-hidden />}
          {copied ? t("reader.notebook_copied") : t("reader.notebook_copy_short")}
        </button>
      </footer>
    </aside>
  );
}
