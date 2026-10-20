// features/reader/annotations/useAnnotations.ts — Les notes d'un document, et ce qu'on en fait.
//
// Deux requêtes : `["annotations", docId]` (surlignages, post-it, signets du
// document) et `["annotation-labels"]` (les étiquettes de l'élève, globales).
// Les éditions et suppressions sont OPTIMISTES : la page répond tout de suite,
// un échec remet l'état d'avant et le dit (le message du serveur est déjà
// traduit). Une création attend l'id du serveur — un aller-retour local.
//
// En lecture seule pendant la visite guidée : le document de démonstration est
// éphémère, rien n'y est écrit.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { toast } from "sonner";

import { api } from "../../../api/client";
import type {
  AnnotationColor,
  AnnotationLabel,
  AnnotationLabelsPayload,
  AnnotationStyle,
  DocumentAnnotations,
  HighlightAnchor,
  ReaderNote,
  SavedHighlight,
} from "../../../api/types";
import { useT } from "../../../i18n";

const EMPTY: DocumentAnnotations = { highlights: [], notes: [] };
const NO_LABELS: AnnotationLabel[] = [];

export interface NewHighlight {
  page: number;
  quote: string;
  rects: number[][];
  anchor: HighlightAnchor | null;
  labelId: number | null;
  style: AnnotationStyle;
}

export type HighlightFields = Partial<{ label_id: number | null; style: AnnotationStyle; note: string | null }>;
export type NoteFields = Partial<{ body: string; label_id: number | null; x: number; y: number }>;

export interface NewNote {
  kind: ReaderNote["kind"];
  page: number;
  x?: number | null;
  y?: number | null;
  body?: string;
  labelId?: number | null;
}

export function useAnnotations(docId: number, { readOnly }: { readOnly: boolean }) {
  const queryClient = useQueryClient();
  const t = useT();
  const key = ["annotations", docId] as const;
  const enabled = Number.isFinite(docId);

  const { data = EMPTY } = useQuery({
    queryKey: key,
    queryFn: () => api.documentAnnotations(docId),
    enabled,
  });
  const { data: labelsPayload } = useQuery({
    queryKey: ["annotation-labels"],
    queryFn: api.annotationLabels,
    enabled,
  });
  const labels = labelsPayload?.labels ?? NO_LABELS;
  // Les bornes de config/settings.py (nom, nombre, couleur proposée) ; null
  // tant que la réponse n'est pas arrivée.
  const limits = labelsPayload
    ? { nameMax: labelsPayload.name_max, maxLabels: labelsPayload.max_labels, defaultColor: labelsPayload.default_color }
    : null;
  const labelsById = useMemo(() => new Map(labels.map((label) => [label.id, label])), [labels]);

  const fail = (err: unknown) => toast.error(err instanceof Error && err.message ? err.message : t("annotations.save_error"));
  const write = (update: (current: DocumentAnnotations) => DocumentAnnotations) =>
    queryClient.setQueryData<DocumentAnnotations>(key, (current) => update(current ?? EMPTY));
  // Le nombre d'éléments par étiquette (gestionnaire d'étiquettes) suit.
  const refreshUsage = () => void queryClient.invalidateQueries({ queryKey: ["annotation-labels"] });

  /** Applique tout de suite, envoie, et revient en arrière si le serveur refuse. */
  function optimistic<T>(apply: (current: DocumentAnnotations) => DocumentAnnotations, send: () => Promise<T>, settle?: (result: T) => void) {
    if (readOnly) return;
    const before = queryClient.getQueryData<DocumentAnnotations>(key);
    write(apply);
    send().then(
      (result) => settle?.(result),
      (err) => {
        queryClient.setQueryData(key, before);
        fail(err);
      },
    );
  }

  async function createHighlight(input: NewHighlight): Promise<SavedHighlight | null> {
    if (readOnly) return null;
    try {
      const { highlight } = await api.createHighlight(docId, {
        page: input.page,
        quote: input.quote,
        rects: input.rects,
        anchor: input.anchor ?? undefined,
        style: input.style,
        ...(input.labelId !== null ? { label_id: input.labelId } : {}),
      });
      // Le même passage surligné deux fois reste UN surlignage : le serveur
      // rend celui qui existait, qu'on remplace au lieu d'empiler une couche.
      write((current) => ({
        ...current,
        highlights: current.highlights.some((h) => h.id === highlight.id)
          ? current.highlights.map((h) => (h.id === highlight.id ? highlight : h))
          : [...current.highlights, highlight],
      }));
      // L'ordre de lecture (celui du carnet et de l'export) est celui du serveur.
      void queryClient.invalidateQueries({ queryKey: key });
      refreshUsage();
      return highlight;
    } catch (err) {
      fail(err);
      return null;
    }
  }

  function updateHighlight(id: number, fields: HighlightFields) {
    optimistic(
      (current) => ({
        ...current,
        highlights: current.highlights.map((h) => (h.id === id ? { ...h, ...fields } : h)),
      }),
      () => api.editHighlight(docId, id, fields),
      ({ highlight }) => {
        write((current) => ({ ...current, highlights: current.highlights.map((h) => (h.id === id ? highlight : h)) }));
        if ("label_id" in fields) refreshUsage();
      },
    );
  }

  function deleteHighlight(id: number) {
    optimistic(
      (current) => ({ ...current, highlights: current.highlights.filter((h) => h.id !== id) }),
      () => api.deleteHighlight(docId, id),
      refreshUsage,
    );
  }

  async function createNote(input: NewNote): Promise<ReaderNote | null> {
    if (readOnly) return null;
    try {
      const { note } = await api.createNote(docId, {
        kind: input.kind,
        page: input.page,
        x: input.x ?? null,
        y: input.y ?? null,
        body: input.body ?? "",
        label_id: input.labelId ?? null,
      });
      // Un signet de plus sur une page qui en a un le remplace (un par page).
      write((current) => ({
        ...current,
        notes: current.notes.some((n) => n.id === note.id)
          ? current.notes.map((n) => (n.id === note.id ? note : n))
          : [...current.notes, note],
      }));
      refreshUsage();
      return note;
    } catch (err) {
      fail(err);
      return null;
    }
  }

  function updateNote(id: number, fields: NoteFields) {
    optimistic(
      (current) => ({ ...current, notes: current.notes.map((n) => (n.id === id ? { ...n, ...fields } : n)) }),
      () => api.editNote(docId, id, fields),
      ({ note }) => {
        write((current) => ({ ...current, notes: current.notes.map((n) => (n.id === id ? note : n)) }));
        if ("label_id" in fields) refreshUsage();
      },
    );
  }

  function deleteNote(id: number) {
    optimistic(
      (current) => ({ ...current, notes: current.notes.filter((n) => n.id !== id) }),
      () => api.deleteNote(docId, id),
      refreshUsage,
    );
  }

  // ── Étiquettes (gestionnaire du carnet) ────────────────────────────────

  function setLabels(update: (current: AnnotationLabel[]) => AnnotationLabel[]) {
    queryClient.setQueryData<AnnotationLabelsPayload>(["annotation-labels"], (current) =>
      current ? { ...current, labels: update(current.labels) } : current,
    );
  }

  async function createLabel(name: string, color: AnnotationColor): Promise<AnnotationLabel | null> {
    if (readOnly) return null;
    try {
      const { label } = await api.createLabel(name, color);
      setLabels((current) => [...current, { ...label, usage: 0 }]);
      return label;
    } catch (err) {
      fail(err);
      return null;
    }
  }

  function updateLabel(id: number, fields: Partial<{ name: string | null; color: AnnotationColor }>) {
    if (readOnly) return;
    const before = queryClient.getQueryData<AnnotationLabelsPayload>(["annotation-labels"]);
    setLabels((current) => current.map((label) => (label.id === id ? { ...label, ...fields } : label)));
    api.editLabel(id, fields).catch((err) => {
      queryClient.setQueryData(["annotation-labels"], before);
      fail(err);
    });
  }

  async function deleteLabel(id: number) {
    if (readOnly) return;
    try {
      await api.deleteLabel(id);
      setLabels((current) => current.filter((label) => label.id !== id));
      // Ses éléments restent, sans étiquette — ici, et dans les autres documents.
      write((current) => ({
        highlights: current.highlights.map((h) => (h.label_id === id ? { ...h, label_id: null } : h)),
        notes: current.notes.map((n) => (n.label_id === id ? { ...n, label_id: null } : n)),
      }));
      void queryClient.invalidateQueries({ queryKey: ["annotations"] });
    } catch (err) {
      fail(err);
    }
  }

  function reorderLabels(ids: number[]) {
    if (readOnly) return;
    const before = queryClient.getQueryData<AnnotationLabelsPayload>(["annotation-labels"]);
    setLabels((current) =>
      ids
        .map((id, position) => {
          const label = current.find((l) => l.id === id);
          return label ? { ...label, position } : null;
        })
        .filter((label): label is AnnotationLabel => label !== null),
    );
    api.orderLabels(ids).catch((err) => {
      queryClient.setQueryData(["annotation-labels"], before);
      fail(err);
    });
  }

  return {
    highlights: data.highlights,
    notes: data.notes,
    labels,
    labelsById,
    limits,
    readOnly,
    createHighlight,
    updateHighlight,
    deleteHighlight,
    createNote,
    updateNote,
    deleteNote,
    createLabel,
    updateLabel,
    deleteLabel,
    reorderLabels,
  };
}

export type Annotations = ReturnType<typeof useAnnotations>;
