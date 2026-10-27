// Quiz.test.tsx — Une réponse rédigée ne fait plus attendre la question
// suivante : Clikoda la corrige en arrière-plan, et sa correction n'apparaît
// qu'au bilan, qui l'attend avant d'enregistrer la séance.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { QuizEvaluation, QuizQuestion } from "../api/types";
import { Quiz } from "./Quiz";

const questions: QuizQuestion[] = [
  { id: 1, question: "Pourquoi 17 % seulement ?", choices: null, answer: "Parce que la maladie est rare.", question_type: "open", category: "maths", source: "reading" },
  { id: 2, question: "Que vaut P(B) ?", choices: null, answer: "La probabilité totale de l'indice.", question_type: "open", category: "maths", source: "reading" },
];

function evaluation(verdict: QuizEvaluation["verdict"], feedback: string, graded = true): QuizEvaluation {
  return { verdict, score: verdict === "correct" ? 1 : verdict === "partial" ? 0.5 : 0, feedback, hint: "", completion: "", expected_answer: "", graded, signals: null };
}

/** Une correction qu'on libère à la main : le test décide quand Clikoda a fini. */
function deferredEvaluation() {
  let resolve!: (e: QuizEvaluation) => void;
  const promise = new Promise<QuizEvaluation>((r) => (resolve = r));
  return { promise, resolve };
}

async function answer(text: string) {
  await userEvent.type(screen.getByRole("textbox", { name: /ta réponse/i }), text);
  await userEvent.click(screen.getByRole("button", { name: "OK" }));
}

describe("Quiz", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    vi.spyOn(api, "quizSubjects").mockResolvedValue([]);
    vi.spyOn(api, "quizOptions").mockResolvedValue({ min_length: 1, max_length: 30, default_length: 2 });
    vi.spyOn(api, "quizQuestions").mockResolvedValue(questions);
    vi.spyOn(api, "submitQuizAnswer").mockResolvedValue({ updated: false, verdict: "correct" });
    vi.spyOn(api, "quizAnalysis").mockResolvedValue({ analysis: "", weak_subjects: [], courses_to_review: [] });
    vi.spyOn(api, "quizFinalize").mockResolvedValue({ ok: true, score: 75, session_id: 7 });
  });

  it("passe à la question suivante sans attendre la correction, et la montre au bilan", async () => {
    const first = deferredEvaluation();
    const second = deferredEvaluation();
    const evaluate = vi.spyOn(api, "quizEvaluate")
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const recordSession = vi.spyOn(api, "quizRecordSession").mockResolvedValue({ session_id: 7, metrics: {} as never });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <Quiz />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /lancer le quiz/i }));

    await answer("La maladie est rare.");
    // La réponse attendue tout de suite, pas de verdict : la correction tourne.
    expect(evaluate).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Parce que la maladie est rare.")).toBeInTheDocument();
    expect(screen.queryByText("Correct")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /suivant/i }));

    await answer("Une constante.");
    await userEvent.click(screen.getByRole("button", { name: /suivant/i }));

    // Le bilan attend les deux corrections avant d'enregistrer la séance.
    expect(await screen.findByText(/corrige tes réponses rédigées/i)).toBeInTheDocument();
    expect(recordSession).not.toHaveBeenCalled();
    await act(async () => {
      first.resolve(evaluation("correct", "Bien vu, le taux de base."));
      second.resolve(evaluation("partial", "Il manque la normalisation."));
    });

    await waitFor(() => expect(recordSession).toHaveBeenCalledTimes(1));
    const sent = recordSession.mock.calls[0][0].answers;
    expect(sent.map((a) => [a.verdict, a.score, a.graded])).toEqual([["correct", 1, true], ["partial", 0.5, true]]);
    expect(screen.getByText("Bien vu, le taux de base.")).toBeInTheDocument();
    expect(screen.getByText("Il manque la normalisation.")).toBeInTheDocument();
    expect(screen.getAllByText("1.5 / 2").length).toBeGreaterThan(0);
  });

  it("fait trancher l'apprenant au bilan quand Clikoda n'a pas pu corriger", async () => {
    vi.spyOn(api, "quizEvaluate").mockResolvedValue(evaluation("", "", false));
    const recordSession = vi.spyOn(api, "quizRecordSession").mockResolvedValue({ session_id: 8, metrics: {} as never });
    vi.spyOn(api, "quizQuestions").mockResolvedValue([questions[0]]);

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <Quiz />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /lancer le quiz/i }));
    await answer("La maladie est rare.");
    await userEvent.click(screen.getByRole("button", { name: /suivant/i }));

    await userEvent.click(await screen.findByRole("button", { name: /je savais/i }));
    await waitFor(() => expect(recordSession).toHaveBeenCalledTimes(1));
    expect(recordSession.mock.calls[0][0].answers[0]).toMatchObject({ verdict: "correct", graded: false });
  });
});
