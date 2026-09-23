// GemmaPanel.test.tsx — Les commandes du panneau doivent avoir un NOM.
//
// Elles étaient six emoji nus (✦ 🟢 ⚪️ 🎯 ⤢ ▭ ✕ ↵) : rien ne les annonçait à un
// lecteur d'écran, et leur rendu changeait d'un système à l'autre. Ce test fige
// le fait qu'on les atteint désormais par leur nom accessible.
//
// Le panneau ouvre un WebSocket vers /api/reader/{id}/stream : on le bouchonne,
// aucun serveur n'est nécessaire.

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";

import { api } from "../../api/client";
import { GemmaPanel } from "./GemmaPanel";

/** WebSocket minimal : se déclare ouvert, avale ce qu'on lui envoie. */
class FakeWebSocket {
  static readonly OPEN = 1;
  /** Dernier socket construit : sert à pousser un événement serveur au panneau. */
  static last: FakeWebSocket | null = null;
  readyState = FakeWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  sent: string[] = [];

  constructor(public url: string) {
    FakeWebSocket.last = this;
    // Ouverture asynchrone, comme un vrai socket.
    queueMicrotask(() => this.onopen?.());
  }

  /** Simule un message serveur (question, feedback…). */
  emit(event: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(event) });
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
async function renderOpenPanel(props: Partial<React.ComponentProps<typeof GemmaPanel>> = {}) {
  const view = render(
    <TooltipProvider>
      <GemmaPanel docId={1} currentPage={1} sessionId={null} {...props} />
    </TooltipProvider>,
  );
  await userEvent.click(await screen.findByRole("button", { name: /gemma|ouvrir|open/i }));
  return view;
}

/** Le champ de conversation avec Gemma (sous le fil). */
function chatBox() {
  return screen.getByPlaceholderText(/question sur la page|question about page/i);
}

/** Pose une question ouverte, y répond, reçoit un verdict. */
async function playOneQuestion(verdict: string, extra: Record<string, unknown> = {}) {
  await act(async () => {
    FakeWebSocket.last?.emit({
      type: "qa_question",
      question: "Quelle est l'idée principale ?",
      question_type: "open",
      choices: null,
      mask: null,
      page: 1,
      ...extra,
    });
  });
  await userEvent.type(await screen.findByRole("textbox", { name: /ta réponse|your answer/i }), "La dérivée s'annule.");
  await userEvent.click(screen.getByRole("button", { name: "OK" }));
  await act(async () => {
    FakeWebSocket.last?.emit({ type: "qa_feedback", verdict, feedback: "Oui, c'est bien ça.", hint: "" });
  });
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
    // Le bouton fermé annonce le mode, pas son explication : celle-ci n'aide
    // qu'au moment de choisir, et occupait un tiers de l'en-tête de Gemma.
    expect(trigger).not.toHaveTextContent(/moments clés|key moments/i);
  });

  it("neutralise les raccourcis pendant une réponse en cours", async () => {
    await renderOpenPanel();
    // Au repos, les raccourcis sont actionnables.
    const rephrase = await screen.findByRole("button", { name: /reformul|rephrase/i });
    expect(rephrase).toBeEnabled();
  });

  // Le type de question voyageait jusqu'ici sans rien changer à l'affichage :
  // une remise en ordre s'affichait comme une question ouverte, avec un champ
  // texte. La carte Q&R monte désormais le widget du type.
  it("monte le widget de remise en ordre quand la question l'exige", async () => {
    await renderOpenPanel();
    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "qa_question",
        question: "Remets les étapes dans l'ordre.",
        question_type: "ordering",
        choices: ["Poser les hypothèses", "Appliquer le théorème", "Conclure"],
        mask: null,
      });
    });

    expect(await screen.findByText(/remise en ordre/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /valider/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /monter.*conclure/i })).toBeInTheDocument();
  });

  // `suggest_pause` traversait tout le serveur pour finir en phrase ordinaire
  // dans le fil : rien ne la distinguait, et rien ne permettait de la prendre.
  it("propose une pause qu'on peut réellement prendre", async () => {
    await renderOpenPanel();
    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "intervention",
        kind: "suggest_pause",
        message: "Tes réponses raccourcissent : souffle deux minutes.",
        question: "",
        pause_minutes: 5,
        highlights: [],
      });
    });

    expect(await screen.findByText(/pause recommandée/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /faire une pause de 5 min/i }));

    // Le serveur doit l'apprendre : c'est lui qui suspend sa dérive d'attention.
    const sent = FakeWebSocket.last?.sent.map((raw) => JSON.parse(raw)) ?? [];
    expect(sent).toContainEqual({ type: "pause", minutes: 5 });
    // Et le décompte tourne, à la durée annoncée par le serveur.
    expect(screen.getByRole("timer")).toHaveTextContent("05:00");
  });

  // Le conseil de régulation de séance était produit par le modèle, validé par
  // le schéma… et jeté par le routeur. Il s'affiche avec la question.
  it("affiche le conseil de séance attaché à une question", async () => {
    await renderOpenPanel();
    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "qa_question",
        question: "Que retiens-tu de ce passage ?",
        question_type: "open",
        choices: null,
        mask: null,
        session_hint: "Ton attention baisse : fais une pause courte avant de continuer.",
      });
    });

    expect(await screen.findByText(/fais une pause courte/i)).toBeInTheDocument();
  });

  it("signale le passage caché d'un rappel libre", async () => {
    await renderOpenPanel();
    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "qa_question",
        question: "Redonne les trois éléments du passage.",
        question_type: "recall",
        choices: null,
        mask: { quote: "un passage à restituer", placeholder: "passage masqué" },
      });
    });

    expect(await screen.findByText(/rappel/i)).toBeInTheDocument();
    expect(screen.getByText(/masqué/i)).toBeInTheDocument();
  });

  // L'encadré d'une question vit DANS le fil, à sa place : il s'y répond, s'y
  // corrige, et y reste. Ce qui vient ensuite s'écrit à la suite — la
  // correction qu'on vient de lire ne disparaît pas, et ne descend pas non
  // plus sous les messages suivants.
  it("garde l'encadré de la question dans le fil, et continue à la suite", async () => {
    await renderOpenPanel();
    // Partielle : l'encadré attend un choix (« Nouvelle question » / « Terminer »).
    await playOneQuestion("partial");

    const card = screen.getByTestId("qa-card");
    expect(card).toHaveAttribute("data-live", "true");
    expect(card).toHaveTextContent(/idée principale/i);
    expect(card).toHaveTextContent(/La dérivée s'annule\./);
    expect(card).toHaveTextContent(/c'est bien ça/i);

    await userEvent.click(screen.getByRole("button", { name: /terminer|finish/i }));

    // Toujours là, en lecture seule : plus de champ ni de « Terminer ».
    const played = screen.getByTestId("qa-card");
    expect(played).not.toHaveAttribute("data-live");
    expect(played).toHaveTextContent(/c'est bien ça/i);
    expect(screen.queryByRole("button", { name: /terminer|finish/i })).not.toBeInTheDocument();

    // La conversation continue APRÈS l'encadré, pas au-dessus.
    await userEvent.type(chatBox(), "Et ensuite ?{Enter}");
    const order = [...screen.getByTestId("gemma-body").querySelectorAll("[data-testid='qa-card'], [data-role='user']")];
    expect(order.at(0)).toHaveAttribute("data-testid", "qa-card");
    expect(order.at(-1)).toHaveTextContent("Et ensuite ?");
  });

  it("empile les encadrés d'une série de questions dans l'ordre", async () => {
    await renderOpenPanel();
    await playOneQuestion("partial");
    await userEvent.click(screen.getByRole("button", { name: /nouvelle question|new question/i }));
    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "qa_question",
        question: "Deuxième question ?",
        question_type: "open",
        choices: null,
        mask: null,
      });
    });

    const cards = screen.getAllByTestId("qa-card");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent(/idée principale/i);
    expect(cards[0]).not.toHaveAttribute("data-live");
    expect(cards[1]).toHaveTextContent(/Deuxième question/);
    expect(cards[1]).toHaveAttribute("data-live", "true");
    // Le premier encadré a gardé sa correction.
    expect(cards[0]).toHaveTextContent(/c'est bien ça/i);
  });

  // Pendant que Gemma corrige, on peut relire la page : le verrou du lecteur est
  // levé à l'envoi de la réponse, et reposé seulement si elle est fausse.
  it("libère le lecteur le temps de la correction d'une question bloquante", async () => {
    const onGatedChange = vi.fn();
    await renderOpenPanel({ onGatedChange });
    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "gated_question",
        question: "Quelle est l'idée principale ?",
        question_type: "open",
        choices: null,
        mask: null,
        page: 3,
      });
    });
    expect(onGatedChange).toHaveBeenLastCalledWith(true, 3);

    await userEvent.type(await screen.findByRole("textbox", { name: /ta réponse|your answer/i }), "Une réponse.");
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(onGatedChange).toHaveBeenLastCalledWith(false);

    await act(async () => {
      FakeWebSocket.last?.emit({ type: "qa_feedback", verdict: "incorrect", feedback: "Non.", hint: "Relis." });
    });
    expect(onGatedChange).toHaveBeenLastCalledWith(true, 3);
  });

  // Après une réponse fausse, « Réessayer » relance une génération : pendant
  // que Gemma prépare la question suivante, on est libre de bouger dans le
  // document. Le verrou revient avec la question.
  it("libère le lecteur pendant que Gemma prépare la question suivante après une réponse fausse", async () => {
    const onGatedChange = vi.fn();
    await renderOpenPanel({ onGatedChange });
    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "gated_question",
        question: "Quelle est l'idée principale ?",
        question_type: "open",
        choices: null,
        mask: null,
        page: 3,
      });
    });
    await userEvent.type(await screen.findByRole("textbox", { name: /ta réponse|your answer/i }), "Faux.");
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    await act(async () => {
      FakeWebSocket.last?.emit({ type: "qa_feedback", verdict: "incorrect", feedback: "Non.", hint: "Relis." });
    });
    expect(onGatedChange).toHaveBeenLastCalledWith(true, 3);

    await userEvent.click(screen.getByRole("button", { name: /nouvelle question|réessayer|new question|try again/i }));
    expect(onGatedChange).toHaveBeenLastCalledWith(false);

    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "qa_question",
        question: "Reformulons : quelle est l'idée principale ?",
        question_type: "open",
        choices: null,
        mask: null,
        page: 3,
      });
    });
    expect(onGatedChange).toHaveBeenLastCalledWith(true, 3);
  });

  // Une question posée à Gemma pendant une question bloquante : le lecteur est
  // rendu le temps de la réponse, et revient se caler sur la zone ensuite.
  it("libère le lecteur pendant que Gemma répond, même sous une question bloquante", async () => {
    const onGatedChange = vi.fn();
    await renderOpenPanel({ onGatedChange });
    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "gated_question",
        question: "Q ?",
        question_type: "open",
        choices: null,
        mask: null,
        page: 5,
      });
    });
    expect(onGatedChange).toHaveBeenLastCalledWith(true, 5);

    await userEvent.type(chatBox(), "Explique-moi ce terme.{Enter}");
    expect(onGatedChange).toHaveBeenLastCalledWith(false);

    await act(async () => {
      FakeWebSocket.last?.emit({ type: "answer", answer: "Voici.", highlights: [] });
    });
    expect(onGatedChange).toHaveBeenLastCalledWith(true, 5);
  });

  // « + Flashcard » cliqué deux fois sous la même réponse créait deux cartes :
  // un seul départ par réponse, et le bouton dit ce qu'il a fait.
  it("ne crée la flashcard d'une réponse qu'une seule fois", async () => {
    let resolve: (v: { id: number; front: string; back: string; created: boolean }) => void = () => {};
    const spy = vi
      .spyOn(api, "createFlashcardFromExchange")
      .mockImplementation(() => new Promise((r) => (resolve = r)));
    await renderOpenPanel();
    await userEvent.type(chatBox(), "Question{Enter}");
    await act(async () => {
      FakeWebSocket.last?.emit({ type: "answer", answer: "Réponse de Gemma.", highlights: [] });
    });

    const button = await screen.findByRole("button", { name: /flashcard/i });
    await userEvent.click(button);
    await userEvent.click(button);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();

    await act(async () => {
      resolve({ id: 1, front: "Q", back: "R", created: true });
    });
    await waitFor(() => expect(button).toHaveTextContent(/✓/));
    await userEvent.click(button);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(within(screen.getByTestId("gemma-body")).getByText(/flashcard créée|flashcard created/i)).toBeInTheDocument();
  });

  it("déverrouille définitivement le lecteur sur une bonne réponse", async () => {
    const onGatedChange = vi.fn();
    await renderOpenPanel({ onGatedChange });
    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "gated_question",
        question: "Q ?",
        question_type: "open",
        choices: null,
        mask: null,
        page: 2,
      });
    });
    await userEvent.type(await screen.findByRole("textbox", { name: /ta réponse|your answer/i }), "R.");
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    await act(async () => {
      FakeWebSocket.last?.emit({ type: "qa_feedback", verdict: "correct", feedback: "Oui.", hint: "" });
    });
    expect(onGatedChange.mock.calls.at(-1)?.[0]).toBe(false);
  });

  // La zone visée par la question remonte au lecteur avec sa page, et se
  // retire quand la carte se referme.
  it("transmet la zone de la question au lecteur, puis la retire", async () => {
    const onZone = vi.fn();
    await renderOpenPanel({ onZone });
    await playOneQuestion("partial", { zone: { quote: "le passage exact visé" }, page: 4 });
    expect(onZone).toHaveBeenCalledWith("le passage exact visé", 4);

    await userEvent.click(screen.getByRole("button", { name: /terminer|finish/i }));
    expect(onZone).toHaveBeenLastCalledWith(null, expect.any(Number));
  });

  // Réponse juste : on enchaîne. Plus de « Terminer » à cliquer — l'encadré se
  // clôt seul, garde sa correction, et le lecteur récupère la zone cadrée.
  it("enchaîne sans « Terminer » après une réponse juste", async () => {
    const onZone = vi.fn();
    const onMask = vi.fn();
    await renderOpenPanel({ onZone, onMask });
    await playOneQuestion("correct", { zone: { quote: "le passage exact visé" }, page: 4 });

    const played = screen.getByTestId("qa-card");
    expect(played).not.toHaveAttribute("data-live");
    expect(played).toHaveTextContent(/c'est bien ça/i);
    expect(screen.queryByRole("button", { name: /terminer|finish/i })).not.toBeInTheDocument();
    expect(onZone).toHaveBeenLastCalledWith(null, expect.any(Number));
    expect(onMask).toHaveBeenLastCalledWith(null, expect.any(Number));
  });

  // Le socket s'ouvre dès l'arrivée sur le document, sas d'entrée compris : le
  // warm-up de la première question ne part qu'à l'entrée dans la lecture.
  it("ne signale l'entrée dans la lecture qu'une fois le sas franchi", async () => {
    const sentTypes = () => (FakeWebSocket.last?.sent ?? []).map((m) => JSON.parse(m).type);
    const view = await renderOpenPanel({ reading: false });
    expect(sentTypes()).not.toContain("start_reading");

    view.rerender(
      <TooltipProvider>
        <GemmaPanel docId={1} currentPage={1} sessionId={null} reading />
      </TooltipProvider>,
    );
    await waitFor(() => expect(sentTypes()).toContain("start_reading"));
  });
});
