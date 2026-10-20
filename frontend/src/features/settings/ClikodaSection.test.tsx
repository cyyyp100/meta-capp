// ClikodaSection.test.tsx — Le modèle de Clikoda devient un réglage.
//
// Avant, le modèle était un nom en dur côté serveur et l'application ne disait
// jamais qu'il manquait : sur une machine qui ne pouvait pas le charger, Clikoda
// se taisait, point. Ces tests figent les trois choses qui comptent ici : les
// modèles proposés viennent du SERVEUR, aucun n'est interdit, et quand il en
// manque un on donne la commande — sans jamais la lancer soi-même.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type LlmStatus, type PreferencesPayload } from "../../api/client";
import { ClikodaSection } from "./ClikodaSection";

function preferences(model = "auto"): PreferencesPayload {
  return {
    preferences: {
      theme: "light", density: "comfortable", text_size: "normal", updates_check: "false",
      tour_done: "true", entry_sas_s: "60", lang_pro_note_dismissed: "false", llm_model: model, llm_economy: "auto", llm_tiny_note_dismissed: "false",
    },
    // Le vocabulaire vient du serveur (la table `LLM_MODELS`), pas du composant.
    choices: {
      theme: [], density: [], text_size: [], updates_check: [], tour_done: [],
      entry_sas_s: [], lang_pro_note_dismissed: [],
      llm_model: ["auto", "gemma4:e2b", "gemma4:e4b", "gemma4:31b"],
      llm_economy: ["auto", "on", "off"], llm_tiny_note_dismissed: [],
    },
    lang: "fr", supported_langs: ["fr", "en"], user: { id: 1, name: "Élève" },
  };
}

function status(extra: Partial<LlmStatus> = {}): LlmStatus {
  return {
    available: true, ollama_up: true, model: "gemma4:e4b", preference: "auto",
    tier: "standard", supports_images: true,
    installed: [{ name: "gemma4:e4b", size_gb: 8.9, known: true, fits: true }],
    catalog: [
      { name: "gemma4:e2b", tier: "small", download_gb: 7.2, min_ram_gb: 8, installed: false, fits: true },
      { name: "gemma4:e4b", tier: "standard", download_gb: 9.6, min_ram_gb: 12, installed: true, fits: true },
      { name: "gemma4:31b", tier: "large", download_gb: 20, min_ram_gb: 32, installed: false, fits: false },
    ],
    ram_gb: 16, fits: true, reason: null, requested_missing: null,
    pull_command: "ollama pull gemma4:e4b",
    throughput: { model: "gemma4:e4b", measured: true, output_tokens_per_s: 27.4, prompt_tokens_per_s: 240, slowdown: 1 },
    economy: false, economy_preference: "auto", economy_reason: null,
    auto_set_aside: [], auto_min_output_tokens_per_s: 15,
    ...extra,
  };
}

async function renderSection(payload = preferences(), state = status()) {
  vi.spyOn(api, "llmStatus").mockResolvedValue(state);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <ClikodaSection payload={payload} />
      </QueryClientProvider>,
    );
  });
}

describe("ClikodaSection", () => {
  beforeEach(() => {
    vi.spyOn(api, "setPreferences").mockImplementation(async (patch) =>
      preferences(String(patch.llm_model ?? "auto")),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("propose les modèles que le serveur déclare, avec ce qu'ils coûtent", async () => {
    await renderSection();
    const models = screen.getByRole("group", { name: /^(modèle|model)$/i });
    expect(within(models).getByRole("button", { name: /automatique|automatic/i })).toBeInTheDocument();
    // Taille et palier, pour choisir en connaissance de cause.
    expect(await screen.findByRole("button", { name: /gemma4:e4b.*9\.6/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /gemma4:31b.*20/i })).toBeInTheDocument();
  });

  it("n'interdit rien : un modèle absent ou trop lourd reste choisissable, et le dit", async () => {
    await renderSection();
    const absent = await screen.findByRole("button", { name: /gemma4:e2b.*7\.2/i });
    const trop = screen.getByRole("button", { name: /gemma4:31b/i });
    expect(absent).not.toBeDisabled();
    expect(trop).not.toBeDisabled();
    expect(absent).toHaveAccessibleName(/pas installé|not installed/i);
    expect(trop).toHaveAccessibleName(/trop lourd|too heavy/i);

    await act(async () => userEvent.click(trop));
    expect(api.setPreferences).toHaveBeenCalledWith({ llm_model: "gemma4:31b" });
  });

  it("dit avec quoi Clikoda tourne, et ce que la machine a sous le capot", async () => {
    await renderSection();
    const state = await screen.findByText(/clikoda tourne avec|clikoda is running/i);
    expect(state).toHaveTextContent("gemma4:e4b");
    expect(state).toHaveTextContent(/16/);       // la RAM détectée
    expect(state).toHaveTextContent(/27[.,]4/);  // la vitesse mesurée ici
  });

  it("donne la commande d'installation à copier, et ne télécharge rien elle-même", async () => {
    await renderSection(preferences(), status({
      available: false, reason: "no_model", installed: [], pull_command: "ollama pull gemma4:e4b",
    }));
    expect(await screen.findByText("ollama pull gemma4:e4b")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copier|copy/i })).toBeInTheDocument();
    // Aucun bouton n'INSTALLE : ce serait un téléchargement lancé par
    // l'application, et cette édition n'a qu'un seul appel sortant.
    const names = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    expect(names.filter((name) => /^(installer|télécharger|install|download)/i.test(name))).toEqual([]);
  });

  it("nomme le modèle manquant quand c'est un choix explicite", async () => {
    await renderSection(preferences("gemma4:31b"), status({
      reason: "model_missing", requested_missing: "gemma4:31b", pull_command: "ollama pull gemma4:31b",
    }));
    expect(await screen.findByText("ollama pull gemma4:31b")).toBeInTheDocument();
    // La phrase nomme le modèle demandé, pas le repli qui tourne en attendant.
    expect(screen.getByText(/gemma4:31b\)/)).toBeInTheDocument();
  });

  it("propose le mode économe dans les deux sens, avec le vocabulaire du serveur", async () => {
    await renderSection();
    const economy = screen.getByRole("group", { name: /mode économe|economy mode/i });
    const buttons = within(economy).getAllByRole("button").map((b) => b.textContent);
    expect(buttons).toHaveLength(3);
    expect(within(economy).getByRole("button", { name: /automatique|automatic/i })).toHaveAttribute("aria-pressed", "true");
    await act(async () => userEvent.click(within(economy).getByRole("button", { name: /coupé|^off$/i })));
    expect(api.setPreferences).toHaveBeenCalledWith({ llm_economy: "off" });
  });

  it("dit si le mode économe est actif, et pourquoi — la raison vient du serveur", async () => {
    await renderSection(preferences(), status({
      model: "qwen3:1.7b", tier: "tiny", supports_images: false,
      economy: true, economy_preference: "auto", economy_reason: "tiny_model",
    }));
    const state = await screen.findByText(/clikoda tourne avec|clikoda is running/i);
    expect(state).toHaveTextContent(/mode économe actif|economy mode on/i);
    expect(state).toHaveTextContent(/plus petit modèle|smallest model/i);
  });

  it("dit pourquoi « Automatique » écarte un modèle plus capable, sans l'interdire", async () => {
    // Le M4 de 16 Go : 12b tient en mémoire mais n'écrit que 11,9 tokens/s.
    const heavy = { name: "gemma4:12b", tier: "standard", download_gb: 8, min_ram_gb: 12, installed: true, fits: true };
    const state = status({
      installed: [
        { name: "gemma4:e4b", size_gb: 8.9, known: true, fits: true },
        { name: "gemma4:12b", size_gb: 7.5, known: true, fits: true, too_slow: true },
      ],
      catalog: [...status().catalog, { ...heavy, too_slow: true }],
      auto_set_aside: [
        { model: "gemma4:12b", output_tokens_per_s: 11.9, prompt_tokens_per_s: 89, measured_at: "2026-10-15T09:12:00+00:00" },
      ],
    });
    const payload = preferences();
    payload.choices.llm_model = [...payload.choices.llm_model, "gemma4:12b"];
    await renderSection(payload, state);

    expect(await screen.findByText(/gemma4:12b (est écarté|is left out).*11[.,]9.*\(15\)/)).toBeInTheDocument();
    const option = screen.getByRole("button", { name: /gemma4:12b/i });
    expect(option).toHaveAccessibleName(/trop lent ici|too slow here/i);
    expect(option).not.toBeDisabled();
  });

  it("ne détaille pas les modèles écartés quand le choix est explicite", async () => {
    await renderSection(preferences("gemma4:e4b"), status({
      preference: "gemma4:e4b",
      auto_set_aside: [{ model: "gemma4:12b", output_tokens_per_s: 11.9, prompt_tokens_per_s: 89, measured_at: null }],
    }));
    await screen.findByText(/clikoda tourne avec|clikoda is running/i);
    expect(screen.queryByText(/est écarté|is left out/)).toBeNull();
  });

  it("dit qu'Ollama est éteint sans le confondre avec un modèle absent", async () => {
    await renderSection(preferences(), status({ available: false, ollama_up: false, reason: "ollama_down" }));
    expect(await screen.findByText(/ollama ne répond pas|ollama is not answering/i)).toBeInTheDocument();
    // Pas de commande `pull` : ce n'est pas ce qu'il manque.
    expect(screen.queryByText(/^ollama pull/)).toBeNull();
  });
});
