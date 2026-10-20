// SelectionToolbar.test.tsx — La barre au-dessus d'une sélection.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AnnotationLabel } from "../../../api/types";
import { useLangStore } from "../../../i18n";
import { loadToolPrefs, saveToolPrefs, SelectionToolbar } from "./SelectionToolbar";

const labels: AnnotationLabel[] = [
  { id: 1, preset: "important", name: null, color: "yellow", position: 0, usage: 0 },
  { id: 2, preset: null, name: "Formule", color: "pink", position: 1, usage: 0 },
];

function renderBar(annotate = true) {
  const handlers = { onContext: vi.fn(), onStyle: vi.fn(), onHighlight: vi.fn(), onNote: vi.fn() };
  render(
    <SelectionToolbar
      x={300}
      y={200}
      rootWidth={900}
      reduceMotion
      toolbarRef={() => {}}
      onContext={handlers.onContext}
      annotate={
        annotate
          ? { labels, style: "underline", labelId: 2, onStyle: handlers.onStyle, onHighlight: handlers.onHighlight, onNote: handlers.onNote }
          : undefined
      }
    />,
  );
  return handlers;
}

describe("SelectionToolbar", () => {
  beforeEach(() => useLangStore.setState({ lang: "fr" }));

  it("propose le contexte, les styles, les étiquettes et la note", async () => {
    const h = renderBar();
    await userEvent.click(screen.getByRole("button", { name: "Contexte" }));
    expect(h.onContext).toHaveBeenCalled();

    expect(screen.getByRole("button", { name: "Souligné" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Barré" }));
    expect(h.onStyle).toHaveBeenCalledWith("strike");

    await userEvent.click(screen.getByRole("button", { name: "Surligner : Important" }));
    expect(h.onHighlight).toHaveBeenCalledWith(1);
    await userEvent.click(screen.getByRole("button", { name: "Surligner : Formule" }));
    expect(h.onHighlight).toHaveBeenCalledWith(2);

    await userEvent.click(screen.getByRole("button", { name: "Note" }));
    expect(h.onNote).toHaveBeenCalled();
  });

  it("n'offre que le contexte pendant la visite guidée", () => {
    renderBar(false);
    expect(screen.getByRole("button", { name: "Contexte" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Surligner/ })).toBeNull();
  });

  it("retient le dernier style et la dernière étiquette", () => {
    saveToolPrefs({ style: "outline", labelId: 7 });
    expect(loadToolPrefs()).toEqual({ style: "outline", labelId: 7 });
    localStorage.setItem("metacapp-annotation-tool", "{pas du json");
    expect(loadToolPrefs()).toEqual({ style: "highlight", labelId: null });
  });
});
