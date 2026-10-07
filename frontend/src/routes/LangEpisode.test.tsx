// LangEpisode.test.tsx — Le sas d'entrée d'une séance de langue.
//
// Deux règles :
//   * une séance s'ouvre sur le sas d'entrée, et son plan n'est demandé qu'une
//     fois le sas franchi — avec le nombre de cartes révisées au warm-up, que
//     le serveur décompte du plafond de cartes de la séance ;
//   * la première visite d'une langue (onboarding, test de niveau) n'a pas de
//     sas : elle enchaîne directement sur la première séance.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type PreferencesPayload } from "../api/client";
import type { Flashcard } from "../api/types";
import { LangEpisode } from "./LangEpisode";

const card = (id: number): Flashcard => ({
  id,
  front: `Question ${id}`,
  back: `Réponse ${id}`,
  tags: [],
  difficulty: 0,
  source: "lang_feuilleton",
  document_title: null,
  chapter_title: null,
});

// Sas réglé sur 30 s : passable à mi-course, après 15 s.
const preferences: PreferencesPayload = {
  preferences: { theme: "light", density: "comfortable", text_size: "normal", updates_check: "false", tour_done: "true", entry_sas_s: "30" },
  choices: { theme: [], density: [], text_size: [], updates_check: [], tour_done: [], entry_sas_s: ["30", "60", "120"] },
  lang: "fr",
  supported_langs: ["fr", "en"],
  user: { id: 1, name: "Élève" },
};

async function wait(seconds: number) {
  for (let i = 0; i < seconds; i++) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  }
}

function renderEpisode(state: Record<string, unknown>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[{ pathname: "/lang/episode", state }]}>
        <Routes>
          <Route path="/lang/episode" element={<LangEpisode />} />
          <Route path="/lang" element={<div>Langues</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LangEpisode", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(api, "preferences").mockResolvedValue(preferences);
    vi.spyOn(api, "langWarmupCards").mockResolvedValue([card(1), card(2)]);
    vi.spyOn(api, "reviewFlashcard").mockResolvedValue({} as Awaited<ReturnType<typeof api.reviewFlashcard>>);
    // Le plan lui-même n'est pas l'objet de ces tests : un échec suffit à
    // savoir s'il a été demandé, et avec quoi.
    vi.spyOn(api, "feuilletonRunStart").mockRejectedValue(new Error("hors sujet"));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("ouvre la séance sur le sas d'entrée des PDF et sa révision de cartes de la langue", async () => {
    renderEpisode({ language: "espagnol", label: "Espagnol" });

    expect(screen.getByText("Espagnol")).toBeInTheDocument();
    expect(api.feuilletonRunStart).not.toHaveBeenCalled();

    // La durée réglée vaut aussi pour une séance de langue.
    await wait(1);
    expect(screen.getByRole("timer")).toHaveTextContent("29");
    await wait(14);
    await act(async () => screen.getByRole("button", { name: /continuer|continue/i }).click());
    expect(api.langWarmupCards).toHaveBeenCalledWith("espagnol");

    for (const text of ["Question 1", "Réponse 1", "Question 2", "Réponse 2"]) {
      await act(async () => screen.getByText(text).click());
    }
    expect(api.feuilletonRunStart).toHaveBeenCalledTimes(1);
    expect(api.feuilletonRunStart).toHaveBeenCalledWith("espagnol", undefined, 2);
  });

  it("n'a pas de sas après l'onboarding d'une nouvelle langue", async () => {
    vi.spyOn(api, "feuilletonOnboarding").mockResolvedValue({ ok: true, next: "zero" });
    renderEpisode({ language: "espagnol", label: "Espagnol", onboarding: true });

    await act(async () => screen.getByRole("button", { name: /continuer|continue/i }).click());
    await act(async () => screen.getByRole("button", { name: /jamais|never/i }).click());

    expect(api.feuilletonRunStart).toHaveBeenCalledWith("espagnol", undefined, 0);
    expect(api.langWarmupCards).not.toHaveBeenCalled();
  });
});
