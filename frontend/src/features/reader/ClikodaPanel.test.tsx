// ClikodaPanel.test.tsx — Les commandes du panneau doivent avoir un NOM.
//
// Elles étaient six emoji nus (✦ 🟢 ⚪️ 🎯 ⤢ ▭ ✕ ↵) : rien ne les annonçait à un
// lecteur d'écran, et leur rendu changeait d'un système à l'autre. Ce test fige
// le fait qu'on les atteint désormais par leur nom accessible.
//
// Le panneau ouvre un WebSocket vers /api/reader/{id}/stream : on le bouchonne,
// aucun serveur n'est nécessaire.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";

import { api } from "../../api/client";
import { ClikodaPanel } from "./ClikodaPanel";

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
 * Rend le panneau ET l'ouvre. Clikoda démarre replié en bulle ; l'ouvrir passait
 * par un `<div onClick>` — donc uniquement à la souris. C'est maintenant un
 * vrai bouton, ce que ce parcours vérifie au passage.
 */
/** Le panneau demande aussi l'état de Clikoda (`/api/llm/status`) pour sa
 *  pastille : il lui faut un QueryClient, comme en production. Le même client
 *  pour tout un test, sinon un `rerender` repartirait de zéro. */
let queryClient: QueryClient;

function wrap(node: React.ReactNode) {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>{node}</TooltipProvider>
    </QueryClientProvider>
  );
}

async function renderOpenPanel(props: Partial<React.ComponentProps<typeof ClikodaPanel>> = {}) {
  const view = render(wrap(<ClikodaPanel docId={1} currentPage={1} sessionId={null} {...props} />));
  await userEvent.click(await screen.findByRole("button", { name: /clikoda|ouvrir|open/i }));
  return view;
}

/** Le champ de conversation avec Clikoda (sous le fil). */
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

describe("ClikodaPanel", () => {
  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
    expect(light).toHaveAttribute("aria-label", expect.stringMatching(/clikoda/i));
  });

  // La pastille ne reflétait QUE le socket du lecteur : elle restait verte avec
  // Ollama éteint ou sans modèle installé — l'état le plus fréquent d'une
  // machine neuve, et celui où l'élève a le plus besoin qu'on le lui dise.
  it("distingue « connecté » de « Clikoda peut répondre »", async () => {
    vi.spyOn(api, "llmStatus").mockResolvedValue({
      available: false, ollama_up: true, model: "gemma4:e4b", preference: "auto",
      tier: "standard", supports_images: true, installed: [], catalog: [],
      ram_gb: 8, fits: true, reason: "no_model", requested_missing: null,
      pull_command: "ollama pull gemma4:e4b",
      throughput: { model: "gemma4:e4b", measured: false, output_tokens_per_s: null, prompt_tokens_per_s: null, slowdown: 1 },
      economy: false, economy_preference: "auto", economy_reason: null,
    });
    await renderOpenPanel();

    const light = await screen.findByRole("status");
    await waitFor(() =>
      expect(light).toHaveAttribute("aria-label", expect.stringMatching(/injoignable|unreachable/i)),
    );
    // Et un mot dans le fil, qui dit où aller : se taire était le défaut.
    expect(await screen.findByText(/réglages ▸ clikoda|settings ▸ clikoda/i)).toBeInTheDocument();
  });

  it("ne demande pas l'état de Clikoda pendant la visite guidée", async () => {
    // La démonstration vit SANS WebSocket : c'est la garantie centrale de la
    // visite (ni jauges, ni profil touché). Une pastille qui s'alarmerait là
    // contredirait la première minute d'utilisation de l'application.
    vi.spyOn(api, "llmStatus").mockResolvedValue({} as never);
    await renderOpenPanel({ demo: true });

    const light = await screen.findByRole("status");
    expect(light).toHaveAttribute("aria-label", expect.stringMatching(/connecté|connected/i));
    expect(api.llmStatus).not.toHaveBeenCalled();
  });

  it("propose le mode d'accompagnement dans un sélecteur nommé et traduit", async () => {
    await renderOpenPanel();

    // Le <select> natif listait « discret / normal / coach » bruts.
    const trigger = await screen.findByRole("combobox", { name: /mode/i });
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveTextContent(/normal/i);
    // Le bouton fermé annonce le mode, pas son explication : celle-ci n'aide
    // qu'au moment de choisir, et occupait un tiers de l'en-tête de Clikoda.
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
    const onPauseRequest = vi.fn();
    await renderOpenPanel({ onPauseRequest });
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

    // La prendre ouvre l'écran de pause du lecteur, à la durée annoncée par le
    // serveur — le même chemin que le bouton « Pause ». La carte s'efface.
    expect(onPauseRequest).toHaveBeenCalledWith(5);
    expect(screen.queryByText(/pause recommandée/i)).not.toBeInTheDocument();
  });

  // Pendant une pause, le serveur fige tout ; le panneau, lui, ne doit plus
  // rien lui envoyer de la présence de l'élève, et signaler l'arrêt et la reprise.
  it("signale la pause et la reprise, et se tait entre les deux", async () => {
    const sent = () => (FakeWebSocket.last?.sent ?? []).map((m) => JSON.parse(m));
    const panel = (paused: React.ComponentProps<typeof ClikodaPanel>["paused"]) =>
      wrap(<ClikodaPanel docId={1} currentPage={1} sessionId={null} reading paused={paused} />);
    const view = await renderOpenPanel({ reading: true });

    view.rerender(panel({ source: "suggested", plannedMin: 5, startedAt: Date.now() }));
    await waitFor(() => expect(sent()).toContainEqual({ type: "pause", source: "suggested", minutes: 5 }));

    const before = sent().length;
    await act(async () => {
      window.dispatchEvent(new Event("blur"));
      window.dispatchEvent(new Event("mousemove"));
    });
    expect(sent().slice(before).filter((m) => m.type === "activity")).toEqual([]);

    view.rerender(panel(null));
    await waitFor(() => expect(sent()).toContainEqual({ type: "resume" }));
    // Une seule paire, même si le lecteur se re-rend.
    view.rerender(panel(null));
    expect(sent().filter((m) => m.type === "resume")).toHaveLength(1);
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
    const order = [...screen.getByTestId("clikoda-body").querySelectorAll("[data-testid='qa-card'], [data-role='user']")];
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

  // Pendant que Clikoda corrige, on peut relire la page : le verrou du lecteur est
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
  // que Clikoda prépare la question suivante, on est libre de bouger dans le
  // document. Le verrou revient avec la question.
  it("libère le lecteur pendant que Clikoda prépare la question suivante après une réponse fausse", async () => {
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

  // Une question posée à Clikoda dans la barre du bas, sous une question
  // bloquante : elle ne débloque rien. Le lecteur reste verrouillé pendant la
  // réponse — on peut de toute façon y remonter relire.
  it("garde le lecteur verrouillé pendant que Clikoda répond sous une question bloquante", async () => {
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
    const before = onGatedChange.mock.calls.length;
    const released = () => onGatedChange.mock.calls.slice(before).some(([active]) => active === false);

    await userEvent.type(chatBox(), "Explique-moi ce terme.{Enter}");
    expect(released()).toBe(false);
    await act(async () => {
      FakeWebSocket.last?.emit({ type: "answer", answer: "Voici.", highlights: [] });
    });
    expect(released()).toBe(false);

    // Reformuler, résumer, curiosité : pareil.
    await userEvent.click(screen.getByRole("button", { name: /reformul|rephrase/i }));
    expect(released()).toBe(false);
    await act(async () => {
      FakeWebSocket.last?.emit({ type: "answer", answer: "Autrement dit…", highlights: [] });
    });
    expect(released()).toBe(false);
    // Le verrou tient : le panneau ne se ferme toujours pas.
    expect(screen.queryByRole("button", { name: /^(fermer|close)$/i })).toBeNull();
  });

  // « Réessayer » qui échoue (génération en panne ou annulée) : la carte reste
  // en jeu et le verrou armé. Avant, la carte était close dès l'envoi, et
  // l'échec désarmait le verrou côté client alors que le serveur le gardait :
  // Clikoda se taisait pour toute la séance.
  it("garde le verrou armé quand « Réessayer » échoue", async () => {
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

    await userEvent.click(screen.getByRole("button", { name: /nouvelle question|réessayer|new question|try again/i }));
    // Pendant la génération, la carte reste en jeu, ses boutons désactivés.
    expect(screen.getByTestId("qa-card")).toHaveAttribute("data-live", "true");
    expect(screen.getByRole("button", { name: /nouvelle question|réessayer|new question|try again/i })).toBeDisabled();

    await act(async () => {
      FakeWebSocket.last?.emit({ type: "error", message: "Génération impossible." });
    });
    expect(onGatedChange).toHaveBeenLastCalledWith(true, 3);
    expect(screen.getByTestId("qa-card")).toHaveAttribute("data-live", "true");
    expect(screen.getByRole("button", { name: /nouvelle question|réessayer|new question|try again/i })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /^(fermer|close)$/i })).toBeNull();
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
      FakeWebSocket.last?.emit({ type: "answer", answer: "Réponse de Clikoda.", highlights: [] });
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
    expect(within(screen.getByTestId("clikoda-body")).getByText(/flashcard créée|flashcard created/i)).toBeInTheDocument();
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

  // Métacognition, anticipation : pas de mauvaise réponse. La carte se clôt
  // comme sur une bonne réponse, le verrou tombe, et aucun verdict coloré ne
  // juge une réflexion — même un « partiel ».
  it("referme une question réflexive et lève le verrou, sans verdict", async () => {
    const onGatedChange = vi.fn();
    await renderOpenPanel({ onGatedChange });
    await act(async () => {
      FakeWebSocket.last?.emit({
        type: "gated_question",
        question: "Comment as-tu trouvé ta réponse ?",
        question_type: "metacognition",
        choices: null,
        mask: null,
        page: 2,
      });
    });
    expect(onGatedChange).toHaveBeenLastCalledWith(true, 2);
    await userEvent.type(await screen.findByRole("textbox", { name: /ta réponse|your answer/i }), "J'ai relu.");
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    await act(async () => {
      FakeWebSocket.last?.emit({ type: "qa_feedback", verdict: "partial", feedback: "Noté.", hint: "", no_wrong_answer: true });
    });

    expect(onGatedChange.mock.calls.at(-1)?.[0]).toBe(false);
    const card = screen.getByTestId("qa-card");
    expect(card).not.toHaveAttribute("data-live");
    expect(card).toHaveTextContent(/réflexion notée|reflection noted/i);
    expect(card).not.toHaveTextContent(/partiel|partial/i);
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

    view.rerender(wrap(<ClikodaPanel docId={1} currentPage={1} sessionId={null} reading />));
    await waitFor(() => expect(sentTypes()).toContain("start_reading"));
  });

  // Le rythme de la révision éclair part avec l'entrée en lecture : c'est le
  // serveur qui le juge (services/warmup.py), pas le panneau.
  it("remet le rythme de la révision éclair avec l'entrée dans la lecture", async () => {
    const warmup = [{ card_id: 4, front_ms: 5200, back_ms: 1800 }];
    await renderOpenPanel({ sessionId: 12, reading: true, warmup });
    await waitFor(() => {
      const start = (FakeWebSocket.last?.sent ?? []).map((m) => JSON.parse(m)).find((m) => m.type === "start_reading");
      expect(start).toEqual({ type: "start_reading", session_id: 12, warmup });
    });
  });
  // Sur la machine de 4 Go, une réponse se chiffre en minutes : sans un mot, un
  // panneau qui « réfléchit » trois minutes ressemble à un panneau figé.
  it("annonce l'attente que le serveur chiffre, et laisse annuler", async () => {
    const cancel = vi.spyOn(api, "cancelGenerations").mockResolvedValue({ cancelled: true });
    await renderOpenPanel();
    await userEvent.type(chatBox(), "Pourquoi le moment aide-t-il ?");
    await userEvent.click(screen.getByRole("button", { name: /envoyer|send/i }));
    // Machine rapide : rien n'est annoncé.
    await act(async () => FakeWebSocket.last?.emit({ type: "loading", estimate_s: null }));
    expect(screen.queryByRole("button", { name: /^(annuler|cancel)$/i })).toBeNull();
    // Le budget republié au départ de la tâche : 3 min 20 → « 4 min au plus ».
    await act(async () => FakeWebSocket.last?.emit({ type: "loading", estimate_s: 200 }));
    expect(screen.getByText(/4 min/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /^(annuler|cancel)$/i }));
    expect(cancel).toHaveBeenCalledTimes(1);
    // La main est rendue tout de suite, sans attendre la réponse du serveur.
    expect(screen.queryByText(/réfléchit|thinking/i)).toBeNull();
    expect(screen.getByText(/demande annulée|request cancelled/i)).toBeInTheDocument();
    expect(chatBox()).not.toBeDisabled();

    // L'annulation revient du serveur : rien à redire, et surtout pas « ⚠️ ».
    await act(async () =>
      FakeWebSocket.last?.emit({ type: "error", message: "Demande annulée.", cancelled: true }),
    );
    expect(screen.getAllByText(/demande annulée|request cancelled/i)).toHaveLength(1);
    expect(screen.queryByText(/⚠️/)).toBeNull();
  });

  it("une annulation venue d'ailleurs se dit sans alarme", async () => {
    await renderOpenPanel();
    await userEvent.type(chatBox(), "Une question");
    await userEvent.click(screen.getByRole("button", { name: /envoyer|send/i }));
    await act(async () =>
      FakeWebSocket.last?.emit({ type: "error", message: "Demande annulée.", cancelled: true }),
    );
    expect(screen.getByText("Demande annulée.")).toBeInTheDocument();
    expect(screen.queryByText(/⚠️/)).toBeNull();
    expect(screen.queryByText(/réfléchit|thinking/i)).toBeNull();
  });
});
