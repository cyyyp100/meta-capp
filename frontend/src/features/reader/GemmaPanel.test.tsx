// GemmaPanel.test.tsx — Les commandes du panneau doivent avoir un NOM.
//
// Elles étaient six emoji nus (✦ 🟢 ⚪️ 🎯 ⤢ ▭ ✕ ↵) : rien ne les annonçait à un
// lecteur d'écran, et leur rendu changeait d'un système à l'autre. Ce test fige
// le fait qu'on les atteint désormais par leur nom accessible.
//
// Le panneau ouvre un WebSocket vers /api/reader/{id}/stream : on le bouchonne,
// aucun serveur n'est nécessaire.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";

import { GemmaPanel } from "./GemmaPanel";

/** WebSocket minimal : se déclare ouvert, avale ce qu'on lui envoie. */
class FakeWebSocket {
  static readonly OPEN = 1;
  readyState = FakeWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  sent: string[] = [];

  constructor(public url: string) {
    // Ouverture asynchrone, comme un vrai socket.
    queueMicrotask(() => this.onopen?.());
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

/**
 * Rend le panneau ET l'ouvre. Gemma démarre replié en bulle ; l'ouvrir passait
 * par un `<div onClick>` — donc uniquement à la souris. C'est maintenant un
 * vrai bouton, ce que ce parcours vérifie au passage.
 */
async function renderOpenPanel() {
  const view = render(
    <TooltipProvider>
      <GemmaPanel docId={1} currentPage={1} sessionId={null} />
    </TooltipProvider>,
  );
  await userEvent.click(await screen.findByRole("button", { name: /gemma|ouvrir|open/i }));
  return view;
}

describe("GemmaPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    // Le panneau mémorise sa position et son état ouvert/fermé dans localStorage.
    localStorage.clear();
  });

  it("s'ouvre au clavier et expose ses commandes par un nom accessible", async () => {
    await renderOpenPanel();

    // Ces trois commandes étaient 🎯, ⤢/▭ et ✕.
    expect(await screen.findByRole("button", { name: /focus/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /flottant|ancrer|float|dock/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /fermer|close/i })).toBeInTheDocument();

    // Le bouton d'envoi était un « ↵ » nu.
    expect(screen.getByRole("button", { name: /envoyer|send/i })).toBeInTheDocument();
  });

  it("annonce l'état de la connexion en toutes lettres", async () => {
    await renderOpenPanel();

    // C'était 🟢 / ⚪️ — deux emoji dont personne ne devine le sens.
    const light = await screen.findByRole("status");
    expect(light).toHaveAttribute("aria-label", expect.stringMatching(/gemma/i));
  });

  it("propose le mode d'accompagnement dans un sélecteur nommé et traduit", async () => {
    await renderOpenPanel();

    // Le <select> natif listait « discret / normal / coach » bruts.
    const trigger = await screen.findByRole("combobox", { name: /mode/i });
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveTextContent(/normal/i);
  });

  it("neutralise les raccourcis pendant une réponse en cours", async () => {
    await renderOpenPanel();
    // Au repos, les raccourcis sont actionnables.
    const rephrase = await screen.findByRole("button", { name: /reformul|rephrase/i });
    expect(rephrase).toBeEnabled();
  });
});
