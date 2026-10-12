// Steps.test.tsx — Une étape qui pose des questions ne se passe pas sans réponse.
//
// Jeux, entraînement de la leçon, deuxième vague, cartes, expression écrite :
// « Continuer » reste grisé, avec sa raison, tant qu'une question attend. Une
// réponse fausse est une réponse. Le ressenti de l'au revoir, lui, reste libre :
// le laisser sans réponse est une mesure de métacognition (lang_runs._nudge).
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../../../api/client";
import type { EpisodeView, GameItem, PointView, RunPlan, RunStep, WritingTask, WritingView } from "../../../api/feuilleton";
import { ExpressionStep } from "./Expression";
import { LeconStep } from "./Lecon";
import { AuRevoirStep, CartesStep, JeuxStep, SecondWaveStep } from "./Steps";
import type { RunTracker } from "./useRunTracker";

const episode: EpisodeView = {
  id: 1, n: 1, title: "", summary: "", teaser: "", format: "dialogue", kind: "normal", family: "latin", dir: "ltr",
  aid_level: null, tone_colors: false, gender_colors: false, glossary: [],
  lines: [{ speaker: "Ana", translation: "Bonjour Pablo", tokens: [{ text: "Hola", w: true }, { text: " ", w: false }, { text: "Pablo", w: true }] }],
};
const plan = { run_id: 7, rtl: false, family: "latin", episodes: { "1": episode } } as unknown as RunPlan;

function tracker(): RunTracker {
  return { push: vi.fn(), advance: vi.fn(), flush: vi.fn(), activeSeconds: () => 0 };
}

function choice(ref: string, options: string[]): GameItem {
  return { ref, kind: "caractere_sens", prompt: { hanzi: ref }, options, expected: options[0], episode_id: 1 };
}

function step(kind: string, content: Record<string, unknown>): RunStep {
  return { key: kind, kind, budget_s: 120, essential: false, ...content };
}

const next = () => screen.getByRole("button", { name: /^continuer$|^continue$/i });

describe("étapes de séance : pas de suite sans réponse", () => {
  afterEach(() => vi.restoreAllMocks());

  it("les jeux attendent une réponse à chaque item, juste ou fausse", () => {
    const onNext = vi.fn();
    const games = [{ kind: "caractere_sens", ease: 1, items: [choice("a", ["chat", "chien", "oiseau"]), choice("b", ["lune", "soleil", "étoile"])] }];
    render(<JeuxStep step={step("jeux", { games })} plan={plan} tracker={tracker()} onNext={onNext} />);

    expect(next()).toBeDisabled();
    expect(screen.getByText(/chaque question|every question/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "chat" }));
    fireEvent.click(next());
    expect(onNext).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "soleil" }));
    expect(next()).toBeEnabled();
    expect(screen.queryByText(/chaque question|every question/i)).toBeNull();
    fireEvent.click(next());
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("l'entraînement de la leçon attend chacun de ses items", () => {
    const point: PointView = { title: "Ser", learner_goal: "", kind: null, observation: "", explanation: "", highlights: [] };
    const items = [choice("c", ["sol", "luna", "mar"])];
    render(<LeconStep step={step("lecon", { episode_ref: 1, point, items, lesson: null })} plan={plan} tracker={tracker()} onNext={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /voir la leçon|see the lesson/i }));
    fireEvent.click(screen.getByRole("button", { name: /s'entraîner|practi[cs]e/i }));

    expect(next()).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "luna" }));
    expect(next()).toBeEnabled();
  });

  it("la deuxième vague attend l'auto-évaluation de chaque phrase", () => {
    const lines = [{ line: 0, translation: "Bonjour Pablo", typing: false }];
    render(<SecondWaveStep step={step("deuxieme_vague", { episode_ref: 1, lines })} plan={plan} tracker={tracker()} onNext={vi.fn()} />);

    expect(next()).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /voir l'original|show the original/i }));
    expect(next()).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /^je ne savais pas$|^i didn't know$/i }));
    expect(next()).toBeEnabled();
  });

  it("les cartes attendent un verdict sur chacune", () => {
    const cards = [{ id: 5, front: "Hola", back: "Bonjour" }];
    render(<CartesStep step={step("cartes", { cards })} plan={plan} tracker={tracker()} onNext={vi.fn()} />);

    expect(next()).toBeDisabled();
    fireEvent.click(screen.getByText("Hola"));
    fireEvent.click(screen.getByRole("button", { name: /^à peu près$|^more or less$/i }));
    expect(next()).toBeEnabled();
  });

  it("l'expression écrite attend au moins un mot", async () => {
    const onNext = vi.fn();
    vi.spyOn(api, "feuilletonWritingSubmit").mockResolvedValue({} as WritingView);
    const task: WritingTask = {
      kind: "repondre", prompt: "Réponds à Pablo.", speaker: null, use_words: [], use_forms: [],
      length: { min: 3, max: 30, unit: "words" }, bank: [], tier_index: 0, explain_lang: "fr", max_chars: 400,
    };
    render(<ExpressionStep step={step("expression", { task, keyboard: null, lang: "es" })} plan={plan} tracker={tracker()} onNext={onNext} />);
    const send = screen.getByRole("button", { name: /envoyer et continuer|send and continue/i });

    expect(send).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "  …  " } });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Hola Pablo" } });
    expect(send).toBeEnabled();
    await act(async () => fireEvent.click(send));
    expect(api.feuilletonWritingSubmit).toHaveBeenCalledWith(7, "Hola Pablo");
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("le ressenti de l'au revoir reste libre", () => {
    const onNext = vi.fn();
    const feeling = { question: "lang.feuilleton.feel.q", options: ["lang.feuilleton.feel.q.bien"] };
    render(<AuRevoirStep step={step("au_revoir", { take_away: null, teaser: "", feeling })} plan={plan} tracker={tracker()} onNext={onNext} />);

    fireEvent.click(screen.getByRole("button", { name: /^terminer$|^finish$/i }));
    expect(onNext).toHaveBeenCalledWith({ feeling: null });
  });
});
