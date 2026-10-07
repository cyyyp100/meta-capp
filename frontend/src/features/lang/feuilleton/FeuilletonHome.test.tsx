// FeuilletonHome.test.tsx — L'accueil d'une langue : la mention du modèle local
// et la correction arrivée après sa séance.
//
// La mention Pro est un texte statique : un encart masquable (une fois pour
// toutes, réglage `lang_pro_note_dismissed`), plus une ligne là où le serveur
// dit que la limite se voit (`pro_hints`). Aucun appel réseau autre que l'API locale.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type PreferencesPayload } from "../../../api/client";
import type { FeuilletonStatus, WritingView } from "../../../api/feuilleton";
import { PRO_EDITION_URL } from "../../../config/links";
import { FeuilletonHome } from "./FeuilletonHome";

function status(extra: Partial<FeuilletonStatus> = {}): FeuilletonStatus {
  return {
    language: "espagnol", flow: "feuilleton", family: "latin", explain_lang: "fr", onboarding_done: true,
    episode_n: 2, next_episode: 3, next_status: "ready", generating: false, bilan_due: false, level: "A1",
    program: { order: 2, size: 270, point: "Saluer" }, words_seen: 40, words_acquired: 3, episodes_played: 2,
    open_run: null, has_placement: true, model: "gemma4:e4b", generation_failures: 0, pro_hints: [],
    unseen_writing: null, ...extra,
  };
}

function preferences(dismissed: "true" | "false"): PreferencesPayload {
  return {
    preferences: { theme: "light", density: "comfortable", text_size: "normal", updates_check: "false", tour_done: "true", entry_sas_s: "60", lang_pro_note_dismissed: dismissed },
    choices: { theme: [], density: [], text_size: [], updates_check: [], tour_done: [], entry_sas_s: [], lang_pro_note_dismissed: [] },
    lang: "fr", supported_langs: ["fr", "en"], user: { id: 1, name: "Élève" },
  };
}

const writing: WritingView = {
  id: 9, run_id: 4, status: "ready", text: "Hoy soy cansado.", seen: false, corrected_at: "2026-10-07 18:00:00",
  task: {
    kind: "repondre", prompt: "Réponds à Ana.", speaker: "Ana", use_words: [], use_forms: [],
    length: { min: 15, max: 40, unit: "words" }, bank: [], tier_index: 0, explain_lang: "fr", max_chars: 1200,
  },
  checks: null,
  feedback: {
    verdict: "partial", corrected: "Hoy estoy cansado.", praise: "Belle phrase.",
    errors: [{ original: "soy cansado", correction: "estoy cansado", error_type: "conjugaison", explanation: "Un état : estar." }],
  },
};

async function renderHome() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <FeuilletonHome language="espagnol" label="Espagnol" rtl={false} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
}

describe("FeuilletonHome", () => {
  beforeEach(() => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("false"));
    vi.spyOn(api, "setPreferences").mockImplementation(async (patch) => ({
      ...preferences(patch.lang_pro_note_dismissed ? "true" : "false"),
    }));
  });
  afterEach(() => vi.restoreAllMocks());

  it("dit les limites du modèle local, avec un lien vers la section Pro du README, et se masque", async () => {
    vi.spyOn(api, "feuilletonStatus").mockResolvedValue(status());
    await renderHome();
    const note = await screen.findByRole("complementary");
    expect(note).toHaveTextContent("gemma4:e4b");
    expect(screen.getByRole("link", { name: /version pro|pro edition/i })).toHaveAttribute("href", PRO_EDITION_URL);
    expect(PRO_EDITION_URL).toBe("https://github.com/cyyyp100/meta-capp#editions--local-vs-pro");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /masquer|hide/i })));
    expect(api.setPreferences).toHaveBeenCalledWith({ lang_pro_note_dismissed: true });
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("ne remontre pas l'encart une fois masqué", async () => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("true"));
    vi.spyOn(api, "feuilletonStatus").mockResolvedValue(status());
    await renderHome();
    await screen.findByText("Espagnol");
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("rappelle la limite là où elle se voit : échecs d'écriture, fin du programme", async () => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("true"));
    vi.spyOn(api, "feuilletonStatus").mockResolvedValue(
      status({ next_status: "failed", generation_failures: 2, pro_hints: ["generation", "program_end"] }),
    );
    await renderHome();
    expect(await screen.findByText(/peine à écrire cet épisode|struggling to write/i)).toBeInTheDocument();
    expect(screen.getByText(/tout le programme|whole programme/i)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /version pro|pro edition/i })).toHaveLength(2);
  });

  it("annonce une correction arrivée après la séance, la montre, puis la marque vue", async () => {
    vi.spyOn(api, "feuilletonStatus").mockResolvedValue(status({ unseen_writing: { id: 9, run_id: 4 } }));
    vi.spyOn(api, "feuilletonWriting").mockResolvedValue(writing);
    vi.spyOn(api, "feuilletonWritingSeen").mockResolvedValue({ ok: true });
    await renderHome();
    expect(await screen.findByText(/ta correction est prête|your correction is ready/i)).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /^voir$|^view$/i })));
    expect(await screen.findByText("Hoy estoy cansado.")).toBeInTheDocument();
    expect(screen.getByText("soy cansado", { selector: "mark" })).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /fermer|close/i })));
    expect(api.feuilletonWritingSeen).toHaveBeenCalledWith(9);
  });
});
