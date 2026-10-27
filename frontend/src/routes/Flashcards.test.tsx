// Flashcards.test.tsx — Les propositions de la relecture hebdomadaire de
// Clikoda : une version corrigée, ou la suppression d'une carte qui renvoie
// au document. Rien ne s'applique sans un clic de l'élève.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/ui/confirm";

import { api } from "../api/client";
import type { FlashcardSuggestion } from "../api/types";
import { Flashcards } from "./Flashcards";

const fix: FlashcardSuggestion = {
  card_id: 1, front: "Que vaut 2 + 2 ?", back: "5", kind: "fix",
  suggested_front: "Que vaut 2 + 2 ?", suggested_back: "4", reason: "Le verso était faux.", checked_at: "2026-10-27 20:00:00",
};
const remove: FlashcardSuggestion = {
  card_id: 2, front: "Que montre la figure 3 ?", back: "La courbe du haut.", kind: "remove",
  suggested_front: null, suggested_back: null, reason: "La carte renvoie à une figure absente.", checked_at: "2026-10-27 20:00:00",
};

describe("Flashcards", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    vi.spyOn(api, "flashcards").mockResolvedValue([]);
    vi.spyOn(api, "flashcardSuggestions").mockResolvedValue([fix, remove]);
  });

  it("montre les propositions de Clikoda et ne les applique qu'au clic", async () => {
    const accept = vi.spyOn(api, "acceptFlashcardSuggestion").mockResolvedValue({ id: 1 });
    const dismiss = vi.spyOn(api, "dismissFlashcardSuggestion").mockResolvedValue({ ok: true });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ConfirmProvider>
          <Flashcards />
        </ConfirmProvider>
      </QueryClientProvider>,
    );

    const [first, second] = await screen.findAllByTestId("flash-suggestion");
    expect(within(first).getByText("Le verso était faux.")).toBeInTheDocument();
    expect(within(second).getByText("Renvoie au document")).toBeInTheDocument();
    expect(accept).not.toHaveBeenCalled();

    await userEvent.click(within(first).getByRole("button", { name: "Appliquer" }));
    await userEvent.click(within(second).getByRole("button", { name: "Garder la mienne" }));
    await waitFor(() => expect(accept).toHaveBeenCalledWith(1));
    expect(dismiss).toHaveBeenCalledWith(2);
    expect(within(second).getByRole("button", { name: "Supprimer la carte" })).toBeInTheDocument();
  });
});
