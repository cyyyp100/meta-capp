// EntrySas.test.tsx — Le sas d'entrée et sa révision éclair.
//
// Trois règles :
//   * à la fin du compte à rebours, le sas ATTEND : c'est l'élève qui décide
//     d'aller aux cartes, rien ne l'y envoie de lui-même ;
//   * la durée du sas est un réglage (`entry_sas_s`) ;
//   * la révision éclair ne se passe pas — aucun bouton pour l'écourter — et
//     son rythme (temps par face) remonte à la sortie du sas.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type PreferencesPayload } from "../../api/client";
import type { Flashcard } from "../../api/types";
import { EntrySas } from "./EntrySas";
import { WarmUp } from "./WarmUp";

const card = (id: number): Flashcard => ({
  id,
  front: `Question ${id}`,
  back: `Réponse ${id}`,
  tags: [],
  difficulty: 2,
  source: "auto",
  document_title: null,
  chapter_title: null,
});

function preferences(entrySas: string): PreferencesPayload {
  return {
    preferences: { theme: "light", density: "comfortable", text_size: "normal", updates_check: "false", tour_done: "true", entry_sas_s: entrySas, lang_pro_note_dismissed: "false" },
    choices: { theme: [], density: [], text_size: [], updates_check: [], tour_done: [], entry_sas_s: ["30", "60", "120"], lang_pro_note_dismissed: [] },
    lang: "fr",
    supported_langs: ["fr", "en"],
    user: { id: 1, name: "Élève" },
  };
}

/** Avance l'horloge seconde par seconde, en laissant React rendre entre deux. */
async function wait(seconds: number) {
  for (let i = 0; i < seconds; i++) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  }
}

function renderSas(onStart = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <EntrySas source={{ kind: "document", docId: 3 }} title="Segmentation 3D" onStart={onStart} />
    </QueryClientProvider>,
  );
  return onStart;
}

describe("EntrySas", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(api, "docHook").mockResolvedValue({ hook: "Une accroche." } as Awaited<ReturnType<typeof api.docHook>>);
    vi.spyOn(api, "sessionStartCards").mockResolvedValue([card(1), card(2)]);
    vi.spyOn(api, "reviewFlashcard").mockResolvedValue({} as Awaited<ReturnType<typeof api.reviewFlashcard>>);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("attend le clic de l'élève à la fin du compte à rebours", async () => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("30"));
    renderSas();

    await wait(45); // bien au-delà des 30 s réglées
    expect(screen.getByRole("timer")).toHaveTextContent("0");
    expect(screen.queryByText("Question 1")).not.toBeInTheDocument();

    const proceed = screen.getByRole("button", { name: /continuer|continue/i });
    expect(proceed).toBeEnabled();
    await act(async () => proceed.click());
    expect(screen.getByText("Question 1")).toBeInTheDocument();
  });

  it("dure ce que l'élève a réglé", async () => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("120"));
    renderSas();

    await wait(1);
    expect(screen.getByRole("timer")).toHaveTextContent("119");
    // Passable à mi-course, et jamais plus tard que 30 s.
    expect(screen.getByRole("button", { name: /disponible|available/i })).toBeDisabled();
    await wait(29);
    expect(screen.getByRole("button", { name: /continuer|continue/i })).toBeEnabled();
  });
});

describe("WarmUp", () => {
  beforeEach(() => {
    vi.spyOn(api, "reviewFlashcard").mockResolvedValue({} as Awaited<ReturnType<typeof api.reviewFlashcard>>);
  });
  afterEach(() => vi.restoreAllMocks());

  it("ne se passe pas, et remonte le temps de chaque face", async () => {
    const onDone = vi.fn();
    render(<WarmUp cards={[card(1), card(2)]} onDone={onDone} />);

    // Seul « Pourquoi ? » est un bouton : rien pour écourter la révision.
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual([expect.stringMatching(/pourquoi|why/i)]);

    for (const text of ["Question 1", "Réponse 1", "Question 2", "Réponse 2"]) {
      await act(async () => screen.getByText(text).click());
    }

    expect(onDone).toHaveBeenCalledTimes(1);
    const timings = onDone.mock.calls[0][0];
    expect(timings.map((t: { card_id: number }) => t.card_id)).toEqual([1, 2]);
    for (const t of timings) {
      expect(t.front_ms).toBeGreaterThanOrEqual(0);
      expect(t.back_ms).toBeGreaterThanOrEqual(0);
    }
  });

  it("ne remonte rien en démonstration", async () => {
    const onDone = vi.fn();
    render(<WarmUp cards={[card(-1)]} onDone={onDone} demo />);
    await act(async () => screen.getByText("Question -1").click());
    await act(async () => screen.getByText("Réponse -1").click());
    expect(onDone).toHaveBeenCalledWith([]);
    expect(api.reviewFlashcard).not.toHaveBeenCalled();
  });
});
