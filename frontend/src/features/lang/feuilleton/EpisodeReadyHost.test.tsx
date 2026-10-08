// EpisodeReadyHost.test.tsx — « Espagnol : l'épisode 3 est prêt », sur toutes les pages.
//
// Seul le PASSAGE à « prêt » s'annonce : un épisode déjà prêt au premier relevé,
// ou relu tel quel au relevé suivant, ne l'est pas une seconde fois.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../../api/client";
import type { UpcomingEpisode } from "../../../api/feuilleton";
import { EpisodeReadyHost, newlyReady, READY_TOAST_MS } from "./EpisodeReadyHost";
import { UPCOMING_KEY, UPCOMING_POLL_IDLE_MS, UPCOMING_POLL_WRITING_MS, upcomingPollMs } from "./useUpcomingEpisodes";

vi.mock("sonner", () => ({ toast: vi.fn() }));

function upcoming(extra: Partial<UpcomingEpisode> = {}): UpcomingEpisode {
  return { language: "espagnol", episode_n: 3, status: "generating", generating: true, relecture_due: false, ...extra };
}

const READY = upcoming({ status: "ready", generating: false });

describe("newlyReady", () => {
  it("n'annonce rien au premier relevé, même un épisode prêt", () => {
    expect(newlyReady(null, [READY])).toEqual([]);
  });

  it("annonce le passage à « prêt », une seule fois", () => {
    expect(newlyReady([upcoming()], [READY])).toEqual([READY]);
    expect(newlyReady([READY], [READY])).toEqual([]);
  });

  it("annonce l'épisode suivant prêt, et une langue apparue avec un épisode prêt", () => {
    expect(newlyReady([READY], [{ ...READY, episode_n: 4 }])).toHaveLength(1);
    expect(newlyReady([], [{ ...READY, language: "anglais" }])).toHaveLength(1);
  });

  it("n'annonce ni un échec ni une écriture en cours", () => {
    expect(newlyReady([upcoming()], [upcoming({ status: "failed", generating: false })])).toEqual([]);
    expect(newlyReady([upcoming({ status: "queued", generating: false })], [upcoming()])).toEqual([]);
  });
});

it("interroge souvent tant qu'un épisode s'écrit, rarement sinon", () => {
  expect(upcomingPollMs([upcoming()])).toBe(UPCOMING_POLL_WRITING_MS);
  expect(upcomingPollMs([READY])).toBe(UPCOMING_POLL_IDLE_MS);
  expect(upcomingPollMs(undefined)).toBe(UPCOMING_POLL_IDLE_MS);
});

function Probe() {
  const location = useLocation();
  const state = location.state as { language?: string } | null;
  return <div data-testid="where">{`${location.pathname} ${state?.language ?? ""}`}</div>;
}

describe("EpisodeReadyHost", () => {
  let client: QueryClient;
  const toastMock = vi.mocked(toast);

  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(api, "languages").mockResolvedValue([
      { code: "espagnol", label: "Espagnol", flag: "🇪🇸", flow: "feuilleton" },
    ]);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    toastMock.mockReset();
  });

  // React Query notifie ses abonnés au tour suivant de la boucle (setTimeout 0).
  async function flush() {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }

  async function renderHost() {
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/reader/7"]}>
          <Routes>
            <Route path="*" element={<><EpisodeReadyHost /><Probe /></>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(client.getQueryState(UPCOMING_KEY)?.status).toBe("success"));
    await flush();
  }

  /** Un relevé de plus, comme celui de l'interrogation périodique. */
  async function poll() {
    await act(async () => {
      await client.refetchQueries({ queryKey: UPCOMING_KEY });
    });
    await flush();
  }

  it("annonce, depuis n'importe quelle page, l'épisode qui vient d'être écrit — numéro et langue", async () => {
    const spy = vi.spyOn(api, "feuilletonUpcoming").mockResolvedValue([upcoming()]);
    await renderHost();
    expect(toastMock).not.toHaveBeenCalled();

    spy.mockResolvedValue([READY]);
    await poll();
    expect(toastMock).toHaveBeenCalledTimes(1);
    const [title, options] = toastMock.mock.calls[0];
    expect(title).toBe("Espagnol : l'épisode 3 est prêt");
    expect(options).toMatchObject({
      id: "episode-ready-espagnol-3",
      description: "Il t'attend sur la page Langues.",
      duration: READY_TOAST_MS,
    });

    await poll(); // relu tel quel : rien de plus
    expect(toastMock).toHaveBeenCalledTimes(1);

    // « Ouvrir » mène à la page Langues, la langue déjà choisie.
    const action = options?.action as unknown as { onClick: () => void };
    await act(async () => action.onClick());
    expect(screen.getByTestId("where")).toHaveTextContent("/lang espagnol");
  });

  it("n'annonce pas un épisode déjà prêt à l'ouverture", async () => {
    vi.spyOn(api, "feuilletonUpcoming").mockResolvedValue([READY]);
    await renderHost();
    await poll();
    expect(toastMock).not.toHaveBeenCalled();
  });

  it("dit qu'une relecture passe d'abord, après plus de 3 jours sans séance", async () => {
    const spy = vi.spyOn(api, "feuilletonUpcoming").mockResolvedValue([upcoming({ relecture_due: true })]);
    await renderHost();
    spy.mockResolvedValue([{ ...READY, relecture_due: true }]);
    await poll();
    expect(toastMock.mock.calls[0][1]).toMatchObject({ description: "Il t'attend après une relecture, sur la page Langues." });
  });
});
