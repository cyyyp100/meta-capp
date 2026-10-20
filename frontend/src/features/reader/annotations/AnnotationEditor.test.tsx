// AnnotationEditor.test.tsx — Éditer un surlignage ou une note.
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/ui/confirm";

import type { AnnotationLabel, ReaderNote, SavedHighlight } from "../../../api/types";
import { useLangStore } from "../../../i18n";
import { AnnotationEditor } from "./AnnotationEditor";

const labels: AnnotationLabel[] = [
  { id: 1, preset: "important", name: null, color: "yellow", position: 0, usage: 1 },
  { id: 2, preset: "definition", name: null, color: "blue", position: 1, usage: 0 },
];

const highlight: SavedHighlight = {
  id: 9,
  page: 3,
  quote: "Un passage clé",
  rects: [[1, 2, 3, 4]],
  color: "key",
  label_id: 1,
  style: "highlight",
  note: null,
};

const note: ReaderNote = {
  id: 4,
  document_id: 1,
  page: 2,
  kind: "sticky",
  x: 10,
  y: 20,
  body: "Idée",
  label_id: 2,
  created_at: "",
  updated_at: "",
};

describe("AnnotationEditor", () => {
  beforeEach(() => useLangStore.setState({ lang: "fr" }));
  afterEach(() => vi.useRealTimers());

  it("change l'étiquette et le style d'un surlignage", async () => {
    const onChange = vi.fn();
    render(
      <ConfirmProvider>
        <AnnotationEditor kind="highlight" item={highlight} labels={labels} onChange={onChange} onDelete={vi.fn()} />
      </ConfirmProvider>,
    );
    expect(screen.getByRole("radio", { name: "Important" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("radio", { name: "Définition" }));
    expect(onChange).toHaveBeenCalledWith({ label_id: 2 });
    await userEvent.click(screen.getByRole("radio", { name: "Encadré" }));
    expect(onChange).toHaveBeenCalledWith({ style: "outline" });
  });

  it("enregistre la note après une pause de frappe, et l'efface vidée", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    render(
      <ConfirmProvider>
        <AnnotationEditor kind="highlight" item={highlight} labels={labels} onChange={onChange} onDelete={vi.fn()} />
      </ConfirmProvider>,
    );
    const field = screen.getByRole("textbox", { name: "Note sur ce passage" });
    fireEvent.change(field, { target: { value: "À retenir" } });
    expect(onChange).not.toHaveBeenCalled();
    act(() => void vi.advanceTimersByTime(700));
    expect(onChange).toHaveBeenCalledWith({ note: "À retenir" });

    fireEvent.change(field, { target: { value: "  " } });
    act(() => void vi.advanceTimersByTime(700));
    expect(onChange).toHaveBeenLastCalledWith({ note: null });
  });

  it("enregistre ce qui est tapé quand l'éditeur se ferme", () => {
    const onChange = vi.fn();
    const view = render(
      <ConfirmProvider>
        <AnnotationEditor kind="note" item={note} labels={labels} onChange={onChange} onDelete={vi.fn()} />
      </ConfirmProvider>,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Texte de la note" }), { target: { value: "Idée revue" } });
    view.unmount();
    expect(onChange).toHaveBeenCalledWith({ body: "Idée revue" });
  });

  it("ajoute le passage au contexte, et supprime après confirmation", async () => {
    const onDelete = vi.fn();
    const onAddToContext = vi.fn();
    render(
      <ConfirmProvider>
        <AnnotationEditor
          kind="highlight"
          item={highlight}
          labels={labels}
          onChange={vi.fn()}
          onDelete={onDelete}
          onAddToContext={onAddToContext}
        />
      </ConfirmProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Ajouter au contexte de Clikoda" }));
    expect(onAddToContext).toHaveBeenCalledWith("Un passage clé");

    await userEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    expect(onDelete).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "Supprimer" }));
    expect(onDelete).toHaveBeenCalled();
  });

  it("ne propose ni style ni contexte pour un post-it", () => {
    render(
      <ConfirmProvider>
        <AnnotationEditor kind="note" item={note} labels={labels} onChange={vi.fn()} onDelete={vi.fn()} />
      </ConfirmProvider>,
    );
    expect(screen.queryByRole("radio", { name: "Souligné" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ajouter au contexte de Clikoda" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Texte de la note" })).toHaveValue("Idée");
  });
});
