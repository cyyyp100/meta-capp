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
    episode_n: 2, next_episode: 3, next_status: "ready", generating: false, bilan_due: false, relecture_due: false,
    level: "A1",
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
    vi.spyOn(api, "feuilletonEnsureNext").mockResolvedValue({ relaunched: [], generating: false });
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

  it("montre pourquoi « Séance courte » et « Bibliothèque » sont inactives", async () => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("true"));
    vi.spyOn(api, "feuilletonStatus").mockResolvedValue(
      status({ next_status: "failed", episodes_played: 0, episode_n: 0, next_episode: 1 }),
    );
    await renderHome();
    const short = await screen.findByRole("button", { name: /séance courte|short session/i });
    const library = screen.getByRole("button", { name: /^bibliothèque$|^library$/i });
    for (const button of [short, library]) {
      expect(button).toBeDisabled();
      // Lisiblement inactif : atténué, et le curseur le dit.
      expect(button).toHaveStyle({ opacity: "0.45", cursor: "not-allowed" });
    }
    expect(short).toHaveAttribute("title", expect.stringMatching(/épisode 1 est écrit|episode 1 is written/i));
    expect(library).toHaveAttribute("title", expect.stringMatching(/premier épisode|first episode/i));
  });

  it("laisse « Séance courte » et « Bibliothèque » actives quand l'épisode est prêt", async () => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("true"));
    vi.spyOn(api, "feuilletonStatus").mockResolvedValue(status());
    await renderHome();
    const short = await screen.findByRole("button", { name: /séance courte|short session/i });
    expect(short).toBeEnabled();
    expect(short).not.toHaveAttribute("title");
    expect(short).toHaveStyle({ cursor: "pointer" });
  });

  it("après plus de 3 jours sans séance, propose la relecture et dit que l'épisode prêt attend", async () => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("true"));
    vi.spyOn(api, "feuilletonStatus").mockResolvedValue(status({ relecture_due: true }));
    await renderHome();
    expect(await screen.findByRole("button", { name: /relire avant l'épisode 3|re-read before episode 3/i })).toBeInTheDocument();
    expect(screen.getByText(/l'épisode 3 est prêt : il t'attend|episode 3 is ready: it waits/i)).toBeInTheDocument();
    // La séance courte jouerait l'épisode : elle attend la relecture, et le dit.
    const short = screen.getByRole("button", { name: /séance courte|short session/i });
    expect(short).toBeDisabled();
    expect(short).toHaveAttribute("title", expect.stringMatching(/après la relecture|after the re-read/i));
    expect(screen.getByRole("button", { name: /juste relire|just re-read/i })).toBeEnabled();
  });

  it("une séance du jour restée ouverte passe avant la relecture imposée", async () => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("true"));
    vi.spyOn(api, "feuilletonStatus").mockResolvedValue(status({ relecture_due: true, open_run: 12 }));
    await renderHome();
    expect(await screen.findByRole("button", { name: /reprendre la séance|resume the session/i })).toBeInTheDocument();
    expect(screen.queryByText(/on relit d'abord|we re-read first/i)).toBeNull();
  });

  it("relance une fois l'épisode suivant qui ne s'écrit pas", async () => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("true"));
    vi.spyOn(api, "feuilletonStatus").mockResolvedValue(status({ next_status: "failed", generation_failures: 1 }));
    await renderHome();
    await screen.findByText("Espagnol");
    expect(api.feuilletonEnsureNext).toHaveBeenCalledTimes(1);
    expect(api.feuilletonEnsureNext).toHaveBeenCalledWith("espagnol");
  });

  it("ne relance rien quand l'épisode est prêt ou déjà en cours d'écriture", async () => {
    vi.spyOn(api, "preferences").mockResolvedValue(preferences("true"));
    const statusSpy = vi.spyOn(api, "feuilletonStatus").mockResolvedValue(status());
    await renderHome();
    await screen.findByText("Espagnol");
    statusSpy.mockResolvedValue(status({ next_status: "generating", generating: true }));
    await renderHome();
    expect(await screen.findByText(/en train de s'écrire|being written/i)).toBeInTheDocument();
    expect(api.feuilletonEnsureNext).not.toHaveBeenCalled();
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
