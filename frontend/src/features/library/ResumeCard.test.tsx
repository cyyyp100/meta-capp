// ResumeCard.test.tsx — La carte « Reprendre » annonce ce qu'il reste au document.
//
// Elle annonçait la médiane des séances, quiz et langues compris : une durée
// sans rapport avec le document, présentée comme une mesure. Elle dit
// maintenant le temps qu'il reste, et que c'est une estimation tant que
// l'allure n'est pas mesurée.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import type { DocumentSummary, ReadingRemaining, ResumePayload } from "../../api/types";
import { TooltipProvider } from "../../components/ui/tooltip";
import { useLangStore } from "../../i18n";
import { ResumeCard } from "./ResumeCard";

const doc = {
  id: 7,
  title: "Analyse — chapitre 3",
  page_count: 120,
  last_page: 40,
  file_missing: false,
} as DocumentSummary;

function remaining(extra: Partial<ReadingRemaining> = {}): ReadingRemaining {
  return { pages: 81, seconds_per_page: 96, minutes: 130, measured: true, samples: 42, scope: "document", ...extra };
}

async function renderCard(payload: ResumePayload, onRelink = vi.fn()) {
  vi.spyOn(api, "libraryResume").mockResolvedValue(payload);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <MemoryRouter>
            <ResumeCard onRelink={onRelink} />
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    );
  });
  return onRelink;
}

describe("ResumeCard", () => {
  beforeEach(() => {
    useLangStore.setState({ lang: "fr" });
    vi.spyOn(api, "streak").mockResolvedValue({ streak: 0, longest_streak: 0 } as Awaited<ReturnType<typeof api.streak>>);
  });
  afterEach(() => vi.restoreAllMocks());

  it("annonce le temps qu'il reste au document, l'allure mesurée en infobulle", async () => {
    await renderCard({ document: doc, remaining: remaining() });
    const label = await screen.findByText("≈ 2 h 10 pour finir");
    expect(screen.queryByText("estimation")).not.toBeInTheDocument();
    await act(async () => label.focus());
    expect(await screen.findByRole("tooltip")).toHaveTextContent(/96 s par page.*42 pages lues/);
  });

  it("dit que c'est une estimation tant que rien n'est mesuré", async () => {
    await renderCard({
      document: doc,
      remaining: remaining({ minutes: 45, measured: false, samples: 0, scope: "default", seconds_per_page: 120 }),
    });
    expect(await screen.findByText("≈ 45 min pour finir")).toBeInTheDocument();
    expect(screen.getByText("estimation")).toBeInTheDocument();
  });

  it("propose de localiser un fichier introuvable", async () => {
    const missing = { ...doc, file_missing: true };
    const onRelink = await renderCard({ document: missing, remaining: remaining() });
    await userEvent.click(await screen.findByRole("button", { name: /localiser/i }));
    expect(onRelink).toHaveBeenCalledWith(missing);
    expect(screen.queryByRole("button", { name: /reprendre la lecture/i })).not.toBeInTheDocument();
  });

  it("ne s'affiche pas sans document", async () => {
    await renderCard({ document: null, remaining: null });
    expect(screen.queryByText(/reprendre/i)).not.toBeInTheDocument();
  });
});
