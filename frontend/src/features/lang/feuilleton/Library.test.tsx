// Library.test.tsx — La bibliothèque d'une langue : ouvrir un épisode dit qu'il
// se charge, ou qu'il n'a pas pu s'ouvrir. Avant, le clic restait sur la liste,
// sans un mot.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../../../api/client";
import { Library } from "./Library";

async function renderLibrary() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <Library language="espagnol" onClose={() => {}} />
      </QueryClientProvider>,
    );
  });
}

describe("Library", () => {
  afterEach(() => vi.restoreAllMocks());

  it("dit qu'un épisode n'a pas pu s'ouvrir, et permet de revenir à la liste", async () => {
    vi.spyOn(api, "feuilletonLibrary").mockResolvedValue([
      { id: 2, n: 2, title: "Le bricolage", summary: "Un résumé.", kind: "normal", format: "dialogue" },
    ]);
    vi.spyOn(api, "feuilletonEpisode").mockRejectedValue(new Error("500"));
    await renderLibrary();

    const item = await screen.findByRole("button", { name: /le bricolage/i });
    await act(async () => fireEvent.click(item));

    expect(await screen.findByRole("alert")).toHaveTextContent(/pas pu s'ouvrir|could not be opened/i);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /tous les épisodes|all episodes/i })));
    expect(await screen.findByRole("button", { name: /le bricolage/i })).toBeInTheDocument();
  });

  it("dit qu'un épisode se charge", async () => {
    vi.spyOn(api, "feuilletonLibrary").mockResolvedValue([
      { id: 2, n: 2, title: "Le bricolage", summary: "Un résumé.", kind: "normal", format: "dialogue" },
    ]);
    vi.spyOn(api, "feuilletonEpisode").mockReturnValue(new Promise(() => {}));
    await renderLibrary();

    const item = await screen.findByRole("button", { name: /le bricolage/i });
    await act(async () => fireEvent.click(item));

    expect(screen.getByRole("status")).toHaveTextContent(/chargement|loading/i);
  });
});
