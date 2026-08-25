// features/library/useLibraryUi.ts — État d'interface de la bibliothèque.
//
// Mêmes idiomes que `useLangStore` (i18n/index.ts) : création au niveau module,
// lecture de localStorage comme valeur initiale, persistance À L'INTÉRIEUR du
// setter, pas de middleware `persist`.
//
// Ce qui est persisté : le dossier sélectionné et les dossiers dépliés — le rail
// doit être retrouvé tel qu'on l'a laissé. Ce qui ne l'est pas : l'élément en
// cours de glissement, qui n'a de sens que le temps du geste.
import { create } from "zustand";

import type { Selection } from "./folderTree";

const STORAGE_KEY = "metacapp-library-ui";

interface Persisted {
  selection: Selection;
  expanded: number[];
}

interface LibraryUiState extends Persisted {
  draggingDocId: number | null;
  draggingFolderId: number | null;
  select: (selection: Selection) => void;
  toggleExpanded: (id: number) => void;
  expand: (ids: number[]) => void;
  setDraggingDocId: (id: number | null) => void;
  setDraggingFolderId: (id: number | null) => void;
}

function loadPersisted(): Persisted {
  const fallback: Persisted = { selection: { kind: "all" }, expanded: [] };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<Persisted>;
    return {
      selection: parsed.selection ?? fallback.selection,
      expanded: Array.isArray(parsed.expanded) ? parsed.expanded : [],
    };
  } catch {
    // Stockage illisible (mode privé, données corrompues) : on repart à neuf
    // plutôt que d'empêcher la bibliothèque de s'afficher.
    return fallback;
  }
}

function persist(state: Persisted): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Quota plein ou stockage refusé : la préférence est perdue, pas la session.
  }
}

export const useLibraryUi = create<LibraryUiState>((set, get) => ({
  ...loadPersisted(),
  draggingDocId: null,
  draggingFolderId: null,

  select: (selection) => {
    set({ selection });
    persist({ selection, expanded: get().expanded });
  },

  toggleExpanded: (id) => {
    const expanded = get().expanded.includes(id)
      ? get().expanded.filter((x) => x !== id)
      : [...get().expanded, id];
    set({ expanded });
    persist({ selection: get().selection, expanded });
  },

  expand: (ids) => {
    const expanded = Array.from(new Set([...get().expanded, ...ids]));
    if (expanded.length === get().expanded.length) return;
    set({ expanded });
    persist({ selection: get().selection, expanded });
  },

  setDraggingDocId: (id) => set({ draggingDocId: id }),
  setDraggingFolderId: (id) => set({ draggingFolderId: id }),
}));
