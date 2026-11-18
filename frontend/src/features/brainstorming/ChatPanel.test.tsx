// ChatPanel.test.tsx — Le bouton d'envoi (↵) doit avoir un nom accessible.
//
// Il n'affichait que le glyphe ↵ : un lecteur d'écran l'annonçait comme un
// bouton sans nom. On le retrouve maintenant par son rôle et son nom.
//
// Le panneau ouvre un WebSocket vers /api/brainstorming/{id}/stream : on le
// bouchonne, aucun serveur n'est nécessaire.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useLangStore } from "../../i18n";
import { ChatPanel } from "./ChatPanel";

/** WebSocket minimal : n'ouvre rien, avale ce qu'on lui envoie. */
class FakeWebSocket {
  static readonly OPEN = 1;
  readyState = FakeWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  constructor(public url: string) {}
  send() {}
  close() {}
}

// Le sélecteur de dossier interroge l'API : il lui faut un QueryClient.
function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ChatPanel discussionId={1} onFolderChange={() => {}} />
    </QueryClientProvider>,
  );
}

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  it("expose le bouton d'envoi par son nom accessible (FR)", () => {
    useLangStore.setState({ lang: "fr" });
    renderPanel();
    expect(screen.getByRole("button", { name: "Envoyer" })).toBeInTheDocument();
  });

  it("expose le bouton d'envoi par son nom accessible (EN)", () => {
    useLangStore.setState({ lang: "en" });
    renderPanel();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });
});
