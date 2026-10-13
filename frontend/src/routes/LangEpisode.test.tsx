// LangEpisode.test.tsx — Le sas d'entrée d'une séance de langue.
//
// Deux règles :
//   * une séance s'ouvre sur le sas d'entrée — l'accroche de Clikoda sur
//     l'épisode à venir, puis les cartes de la langue —, et son plan n'est
//     demandé qu'une fois le sas franchi, avec le nombre de cartes révisées au
//     warm-up, que le serveur décompte du plafond de cartes de la séance ;
//   * la première visite d'une langue (onboarding, test de niveau) n'a pas de
//     sas : elle enchaîne directement sur la première séance ;
//   * une relecture imposée par plus de 3 jours d'absence n'a aucun sas — ni
//     d'entrée, ni de sortie, ni de repos — mais garde ses cartes, dans la séance.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type PreferencesPayload } from "../api/client";
import type { RunCompletion, RunPlan } from "../api/feuilleton";
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
  preferences: { theme: "light", density: "comfortable", text_size: "normal", updates_check: "false", tour_done: "true", entry_sas_s: "30", lang_pro_note_dismissed: "false" , llm_model: "auto"},
  choices: { theme: [], density: [], text_size: [], updates_check: [], tour_done: [], entry_sas_s: ["30", "60", "120"], lang_pro_note_dismissed: [], llm_model: ["auto"] },
  lang: "fr",
  supported_langs: ["fr", "en"],
  user: { id: 1, name: "Élève" },
};

/** Une relecture imposée par l'absence, telle que le serveur la construit : sans au revoir. */
function relecturePlan(): RunPlan {
  return {
    version: 2, run_id: 7, status: "in_progress", current_step: null, done_steps: [], resumed: false, effective_s: 0,
    mode: "reprise", language: "espagnol", family: "latin", rtl: false, target_s: 1080, max_s: 1500, idle_cutoff_s: 90,
    episodes: {}, episode_id: null, episode_n: null, absence: { days: 5, tier: "rappel_long" }, sas: false,
    tone: "encourager",
    steps: [
      { key: "accueil", kind: "accueil", budget_s: 120, essential: false, variant: "reprise", kept_episode: 3 },
      { key: "cartes", kind: "cartes", budget_s: 180, essential: true, cards: [{ ...card(5), front: "Hola", back: "Bonjour" }] },
    ],
  };
}

function completion(extra: Partial<RunCompletion> = {}): RunCompletion {
  return {
    ok: true, mode: "reprise", episode: null, point: null, new_words: [], cards_created: 0, words_seen: 40,
    words_acquired: 3, acquired_today: 0, units_acquired_today: 0, suggest_rewind: null, writing: null, ...extra,
  };
}

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
    vi.spyOn(api, "feuilletonHook").mockResolvedValue({ hook: "Pablo arrive encore en retard : qui l'attend sur la place ?" });
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
    expect(screen.getByText("Pablo arrive encore en retard : qui l'attend sur la place ?")).toBeInTheDocument();
    expect(api.feuilletonHook).toHaveBeenCalledWith("espagnol");
    await wait(14);
    await act(async () => screen.getByRole("button", { name: /continuer|continue/i }).click());
    expect(api.langWarmupCards).toHaveBeenCalledWith("espagnol");

    for (const text of ["Question 1", "Réponse 1", "Question 2", "Réponse 2"]) {
      await act(async () => screen.getByText(text).click());
    }
    expect(api.feuilletonRunStart).toHaveBeenCalledTimes(1);
    expect(api.feuilletonRunStart).toHaveBeenCalledWith("espagnol", 2);
  });

  it("n'a pas de sas après l'onboarding d'une nouvelle langue", async () => {
    vi.spyOn(api, "feuilletonOnboarding").mockResolvedValue({ ok: true, next: "zero" });
    renderEpisode({ language: "espagnol", label: "Espagnol", onboarding: true });

    await act(async () => screen.getByRole("button", { name: /continuer|continue/i }).click());
    await act(async () => screen.getByRole("button", { name: /jamais|never/i }).click());

    expect(api.feuilletonRunStart).toHaveBeenCalledWith("espagnol", 0);
    expect(api.langWarmupCards).not.toHaveBeenCalled();
    expect(api.feuilletonHook).not.toHaveBeenCalled();
  });

  describe("relecture imposée par l'absence", () => {
    beforeEach(() => {
      vi.spyOn(api, "feuilletonRunStart").mockResolvedValue(relecturePlan());
      vi.spyOn(api, "feuilletonEvents").mockResolvedValue({ ok: true, effective_s: 0, cap_reached: false, skip_to: null });
    });

    async function playThrough() {
      await act(async () => screen.getByRole("button", { name: /^continuer$|^continue$/i }).click());
      // Les cartes sont toujours là : retournée, jugée.
      await act(async () => screen.getByText("Hola").click());
      await act(async () => screen.getByRole("button", { name: /je savais|i knew it/i }).click());
      await act(async () => screen.getByRole("button", { name: /^continuer$|^continue$/i }).click());
    }

    it("n'a ni sas d'entrée ni sas de sortie, et garde ses cartes", async () => {
      vi.spyOn(api, "feuilletonComplete").mockResolvedValue(completion());
      renderEpisode({ language: "espagnol", label: "Espagnol", sas: false });
      await act(async () => {});

      // Pas de sas d'entrée : ni compte à rebours, ni warm-up, ni accroche.
      expect(screen.queryByRole("timer")).toBeNull();
      expect(api.langWarmupCards).not.toHaveBeenCalled();
      expect(api.feuilletonHook).not.toHaveBeenCalled();
      expect(api.feuilletonRunStart).toHaveBeenCalledWith("espagnol", 0);
      expect(screen.getByText(/content de te revoir|good to see you again/i)).toBeInTheDocument();

      await playThrough();
      expect(api.feuilletonComplete).toHaveBeenCalledWith(7, "fini", null);
      // Ni écran de fin ni sas de repos : retour direct aux langues.
      expect(screen.getByText("Langues")).toBeInTheDocument();
      expect(screen.queryByText(/séance terminée|session complete/i)).toBeNull();
      expect(screen.queryByText(/pause de consolidation|consolidation pause/i)).toBeNull();
    });

    it("propose encore de reculer après un contrôle raté, puis ramène aux langues", async () => {
      vi.spyOn(api, "feuilletonComplete").mockResolvedValue(completion({ suggest_rewind: 3 }));
      renderEpisode({ language: "espagnol", label: "Espagnol", sas: false });
      await act(async () => {});
      await playThrough();

      expect(screen.getByText(/relire les 3 derniers épisodes|re-read the last 3 episodes/i)).toBeInTheDocument();
      expect(screen.queryByText(/séance terminée|session complete/i)).toBeNull();
      await act(async () => screen.getByRole("button", { name: /fermer|close/i }).click());
      expect(screen.getByText("Langues")).toBeInTheDocument();
    });
  });
});
