// FindBar.test.tsx — La barre de recherche du lecteur parle comme un navigateur.
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FindSummary } from "../../../api/types";
import { useLangStore } from "../../../i18n";
import { FindBar } from "./FindBar";

function summary(extra: Partial<FindSummary> = {}): FindSummary {
  return {
    query: "equation", total: 17, pages: [{ page: 2, count: 17 }], searchable: true, too_short: false, ...extra,
  };
}

function renderBar(props: Partial<React.ComponentProps<typeof FindBar>> = {}) {
  const handlers = { onQuery: vi.fn(), onNext: vi.fn(), onPrev: vi.fn(), onClose: vi.fn() };
  render(
    <FindBar
      query="équation"
      summary={summary()}
      searching={false}
      ordinal={2}
      locked={false}
      focusToken={1}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe("FindBar", () => {
  beforeEach(() => useLangStore.setState({ lang: "fr" }));

  it("annonce « 3 / 17 » aux lecteurs d'écran, dans un rôle de recherche", () => {
    renderBar();
    expect(screen.getByRole("search")).toBeInTheDocument();
    const count = screen.getByText("3 / 17");
    expect(count).toHaveAttribute("aria-live", "polite");
  });

  it("prend le focus à l'ouverture", () => {
    renderBar();
    expect(screen.getByRole("textbox")).toHaveFocus();
  });

  it("Entrée avance, Maj+Entrée recule, Échap ferme", async () => {
    const { onNext, onPrev, onClose } = renderBar();
    const input = screen.getByRole("textbox");
    await userEvent.type(input, "{Enter}");
    expect(onNext).toHaveBeenCalledTimes(1);
    await userEvent.type(input, "{Shift>}{Enter}{/Shift}");
    expect(onPrev).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("transmet la frappe", async () => {
    const { onQuery } = renderBar({ query: "" });
    await userEvent.type(screen.getByRole("textbox"), "x");
    expect(onQuery).toHaveBeenCalledWith("x");
  });

  it("dit qu'il n'y a rien, ou rien à chercher, plutôt qu'un compteur à zéro", () => {
    renderBar({ summary: summary({ total: 0, pages: [] }), ordinal: -1 });
    expect(screen.getByText("Aucun résultat")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /suivant/i })).toBeDisabled();
  });

  it("dit qu'un PDF scanné n'a pas de texte", () => {
    renderBar({ summary: summary({ total: 0, pages: [], searchable: false }), ordinal: -1 });
    expect(screen.getByText(/n'a pas de texte/)).toBeInTheDocument();
  });

  it("dit qu'il cherche, puis qu'une occurrence est sous la question bloquante", () => {
    const { unmount } = render(
      <FindBar query="équ" summary={undefined} searching ordinal={-1} locked={false} focusToken={0}
               onQuery={vi.fn()} onNext={vi.fn()} onPrev={vi.fn()} onClose={vi.fn()} />,
    );
    expect(screen.getByText("Recherche…")).toBeInTheDocument();
    unmount();
    renderBar({ locked: true });
    expect(screen.getByText(/3 \/ 17 · plus bas que la question en cours/)).toBeInTheDocument();
  });
});
