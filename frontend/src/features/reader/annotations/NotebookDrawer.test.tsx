// NotebookDrawer.test.tsx — Le carnet : filtres, recherche pliée, aller à, export.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/ui/confirm";

import { api } from "../../../api/client";
import type { AnnotationLabel, ReaderNote, SavedHighlight } from "../../../api/types";
import { useLangStore } from "../../../i18n";
import { clampNotebookWidth, loadNotebookWidth, NOTEBOOK_MIN_WIDTH, NOTEBOOK_WIDTH, NotebookDrawer, saveNotebookWidth } from "./NotebookDrawer";
import type { Annotations } from "./useAnnotations";

const labels: AnnotationLabel[] = [
  { id: 1, preset: "important", name: null, color: "yellow", position: 0, usage: 2 },
  { id: 2, preset: "definition", name: null, color: "blue", position: 1, usage: 1 },
];

const hl = (id: number, page: number, quote: string, over: Partial<SavedHighlight> = {}): SavedHighlight => ({
  id,
  page,
  quote,
  rects: [[10, id * 10, 50, id * 10 + 8]],
  color: "key",
  label_id: 1,
  style: "highlight",
  note: null,
  ...over,
});

const note = (id: number, page: number, kind: ReaderNote["kind"], body: string): ReaderNote => ({
  id,
  document_id: 5,
  page,
  kind,
  x: kind === "sticky" ? 20 : null,
  y: kind === "sticky" ? 40 : null,
  body,
  label_id: 2,
  created_at: "",
  updated_at: "",
});

function annotations(): Annotations {
  return {
    highlights: [
      hl(1, 3, "Une Équation différentielle"),
      hl(2, 1, "La définition du produit scalaire", { label_id: 2, note: "À revoir avant l'examen" }),
      hl(3, 40, "Passage d'une page disparue"),
    ],
    notes: [note(7, 3, "sticky", "Penser au cas limite"), note(8, 2, "signet", "Chapitre 2")],
    labels,
    labelsById: new Map(labels.map((l) => [l.id, l])),
    limits: { nameMax: 40, maxLabels: 24, defaultColor: "yellow" },
    readOnly: false,
    createHighlight: vi.fn(),
    updateHighlight: vi.fn(),
    deleteHighlight: vi.fn(),
    createNote: vi.fn(async () => null),
    updateNote: vi.fn(),
    deleteNote: vi.fn(),
    createLabel: vi.fn(),
    updateLabel: vi.fn(),
    deleteLabel: vi.fn(),
    reorderLabels: vi.fn(),
  } as unknown as Annotations;
}

function renderDrawer(data = annotations(), width = NOTEBOOK_WIDTH) {
  const onGoTo = vi.fn();
  const onResize = vi.fn();
  render(
    <ConfirmProvider>
      <NotebookDrawer
        docId={5}
        pageCount={12}
        currentPage={4}
        bookmark={6}
        annotations={data}
        width={width}
        onResize={onResize}
        onClose={vi.fn()}
        onGoTo={onGoTo}
        onAddToContext={vi.fn()}
      />
    </ConfirmProvider>,
  );
  return { onGoTo, onResize, data };
}

describe("NotebookDrawer", () => {
  beforeEach(() => useLangStore.setState({ lang: "fr" }));
  afterEach(() => vi.restoreAllMocks());

  it("range les éléments par page, dans l'ordre du document", () => {
    renderDrawer();
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Page 1", "Page 3", "Page 40"]);
    expect(screen.getByText("Marque-page · page 6")).toBeInTheDocument();
    expect(screen.getByText("Chapitre 2")).toBeInTheDocument();
  });

  it("filtre par étiquette, par type et par note", async () => {
    renderDrawer();
    const labelsGroup = screen.getByRole("group", { name: "Étiquettes" });
    await userEvent.click(within(labelsGroup).getByRole("button", { name: /Définition/ }));
    expect(screen.queryByText("Une Équation différentielle")).toBeNull();
    expect(screen.getByText("La définition du produit scalaire")).toBeInTheDocument();
    await userEvent.click(within(labelsGroup).getByRole("button", { name: /Définition/ }));

    await userEvent.click(screen.getByRole("button", { name: "Post-it" }));
    expect(screen.getByText("Penser au cas limite")).toBeInTheDocument();
    expect(screen.queryByText("La définition du produit scalaire")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Post-it" }));

    await userEvent.click(screen.getByRole("button", { name: "Avec note" }));
    expect(screen.getByText("La définition du produit scalaire")).toBeInTheDocument();
    expect(screen.queryByText("Une Équation différentielle")).toBeNull();
  });

  it("cherche sans tenir compte des accents ni de la casse", async () => {
    renderDrawer();
    await userEvent.type(screen.getByRole("searchbox", { name: "Chercher dans mes notes" }), "equation");
    expect(screen.getByText("Une Équation différentielle")).toBeInTheDocument();
    expect(screen.queryByText("La définition du produit scalaire")).toBeNull();
    await userEvent.clear(screen.getByRole("searchbox"));
    await userEvent.type(screen.getByRole("searchbox"), "examen");
    expect(screen.getByText("La définition du produit scalaire")).toBeInTheDocument();
  });

  it("amène le lecteur sur un élément, pas sur une page disparue", async () => {
    const { onGoTo } = renderDrawer();
    await userEvent.click(screen.getByText("Une Équation différentielle"));
    expect(onGoTo).toHaveBeenCalledWith({ kind: "highlight", id: 1, page: 3 });
    await userEvent.click(screen.getByText("Penser au cas limite"));
    expect(onGoTo).toHaveBeenCalledWith({ kind: "note", id: 7, page: 3 });
    await userEvent.click(screen.getByText("Marque-page · page 6"));
    expect(onGoTo).toHaveBeenCalledWith({ kind: "page", page: 6 });

    expect(screen.getByText("Passage d'une page disparue").closest("button")).toBeDisabled();
  });

  it("pose un signet sur la page courante", async () => {
    const { data } = renderDrawer();
    await userEvent.click(screen.getByRole("button", { name: /Signet sur la page 4/ }));
    expect(data.createNote).toHaveBeenCalledWith({ kind: "signet", page: 4, labelId: 1 });
  });

  it("exporte en téléchargement, et copie le Markdown", async () => {
    const markdown = vi.spyOn(api, "annotationsMarkdown").mockResolvedValue("# Notes");
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderDrawer();
    const link = screen.getByRole("link", { name: /Exporter/ });
    expect(link).toHaveAttribute("href", "/api/library/doc/5/annotations.md");
    expect(link).toHaveAttribute("download");

    await userEvent.click(screen.getByRole("button", { name: /Copier en Markdown/ }));
    expect(markdown).toHaveBeenCalledWith(5);
    expect(writeText).toHaveBeenCalledWith("# Notes");
    expect(await screen.findByText("Copié")).toBeInTheDocument();
  });

  it("s'élargit au clavier, et revient à la largeur par défaut au double-clic", async () => {
    const { onResize } = renderDrawer(annotations(), 400);
    const handle = screen.getByRole("separator", { name: "Largeur du carnet" });
    expect(handle).toHaveAttribute("aria-valuenow", "400");
    expect(screen.getByRole("complementary", { name: "Carnet" })).toHaveStyle({ width: "400px" });

    handle.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onResize).toHaveBeenLastCalledWith(416, true);
    await userEvent.keyboard("{Shift>}{ArrowLeft}{/Shift}");
    expect(onResize).toHaveBeenLastCalledWith(336, true);
    await userEvent.keyboard("{Home}");
    expect(onResize).toHaveBeenLastCalledWith(NOTEBOOK_MIN_WIDTH, true);

    await userEvent.dblClick(handle);
    expect(onResize).toHaveBeenLastCalledWith(NOTEBOOK_WIDTH, true);
  });

  it("borne la largeur à la fenêtre et la retient", () => {
    // Fenêtre de 900 px : le document garde 320 px.
    expect(clampNotebookWidth(2000, 900)).toBe(580);
    expect(clampNotebookWidth(100, 900)).toBe(NOTEBOOK_MIN_WIDTH);
    saveNotebookWidth(452);
    expect(loadNotebookWidth()).toBe(clampNotebookWidth(452));
    localStorage.setItem("metacapp-notebook-width", "pas un nombre");
    expect(loadNotebookWidth()).toBe(clampNotebookWidth(NOTEBOOK_WIDTH));
  });
});
