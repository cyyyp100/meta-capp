// Lang.test.tsx — La page Langues : « En attente » sur la carte d'une langue
// dont l'épisode suivant est écrit et pas encore joué, et la langue ouverte
// d'emblée quand on y arrive depuis l'annonce « épisode prêt ».
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type PreferencesPayload } from "../api/client";
import type { FeuilletonStatus } from "../api/feuilleton";
import { Lang } from "./Lang";

const preferences: PreferencesPayload = {
  preferences: { theme: "light", density: "comfortable", text_size: "normal", updates_check: "false", tour_done: "true", entry_sas_s: "60", lang_pro_note_dismissed: "true" },
  choices: { theme: [], density: [], text_size: [], updates_check: [], tour_done: [], entry_sas_s: [], lang_pro_note_dismissed: [] },
  lang: "fr",
  supported_langs: ["fr", "en"],
  user: { id: 1, name: "Élève" },
};

function status(language: string): FeuilletonStatus {
  return {
    language, flow: "feuilleton", family: "latin", explain_lang: "fr", onboarding_done: true,
    episode_n: 2, next_episode: 3, next_status: "ready", generating: false, bilan_due: false, relecture_due: false,
    level: "A1", program: { order: 2, size: 270, point: "Saluer" }, words_seen: 40, words_acquired: 3,
    episodes_played: 2, open_run: null, has_placement: true, model: "gemma4:e4b", generation_failures: 0,
    pro_hints: [], unseen_writing: null,
  };
}

async function renderLang(state?: Record<string, unknown>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[{ pathname: "/lang", state }]}>
          <Routes>
            <Route path="/lang" element={<Lang />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
}

describe("Lang", () => {
  beforeEach(() => {
    vi.spyOn(api, "languages").mockResolvedValue([
      { code: "anglais", label: "Anglais", flag: "🇬🇧", flow: "feuilleton" },
      { code: "espagnol", label: "Espagnol", flag: "🇪🇸", flow: "feuilleton" },
      { code: "allemand", label: "Allemand", flag: "🇩🇪", flow: "feuilleton" },
    ]);
    vi.spyOn(api, "feuilletonUpcoming").mockResolvedValue([
      { language: "anglais", episode_n: 3, status: "ready", generating: false, relecture_due: false },
      { language: "espagnol", episode_n: 4, status: "generating", generating: true, relecture_due: false },
    ]);
    vi.spyOn(api, "preferences").mockResolvedValue(preferences);
    vi.spyOn(api, "feuilletonStatus").mockImplementation(async (language) => status(language));
    vi.spyOn(api, "feuilletonEnsureNext").mockResolvedValue({ relaunched: [], generating: false });
  });
  afterEach(() => vi.restoreAllMocks());

  it("marque « En attente » la langue dont l'épisode est prêt, et elle seule", async () => {
    await renderLang();
    const english = await screen.findByRole("button", { name: /anglais/i });
    const badge = await within(english).findByText("En attente");
    expect(badge).toHaveAttribute("title", "Épisode 3 prêt, en attente de passage");
    expect(within(screen.getByRole("button", { name: /espagnol/i })).queryByText("En attente")).toBeNull();
    expect(within(screen.getByRole("button", { name: /allemand/i })).queryByText("En attente")).toBeNull();
  });

  it("ouvre d'emblée la langue que l'annonce désigne", async () => {
    await renderLang({ language: "anglais" });
    expect(await screen.findByRole("heading", { name: "Anglais" })).toBeInTheDocument();
    expect(api.feuilletonStatus).toHaveBeenCalledWith("anglais");
  });
});
