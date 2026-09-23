import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import {
  Coffee,
  CornerDownLeft,
  Lightbulb,
  Maximize2,
  PanelRight,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { Rnd } from "react-rnd";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { api } from "../../api/client";
import { wsTokenSuffix } from "../../api/security";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
import type { ReadingPause } from "../session/PauseSas";
import { AnswerInput } from "../questions/AnswerInput";
import { QuestionStem } from "../questions/QuestionStem";
import { QuestionTypeBadge } from "../questions/QuestionTypeBadge";
import { VerdictBadge } from "../questions/VerdictBadge";
import { DEMO_BEATS, DEMO_QUESTION, DEMO_QUOTES, DEMO_THINKING_MS, type DemoBeat } from "./demoScript";
import { renderMathToHtml } from "./renderMath";

interface QaFeedback {
  verdict: string;
  feedback: string;
  hint?: string;
}

/**
 * Une question de Gemma, DANS le fil, à sa place chronologique. C'est le même
 * encadré qui se répond (question en jeu), qui se corrige, et qui reste
 * ensuite comme trace : ce qui vient après — une autre question, une
 * conversation — s'écrit à la suite, jamais au-dessus. Un seul encadré est
 * « en jeu » à la fois (`liveQaId`) ; les autres sont en lecture seule.
 */
interface QaRecord {
  id: number;
  question: string;
  type: string;
  choices: string[] | null;
  mask: QaMask | null;
  /** Conseil de régulation de séance (`session_hint`), vide la plupart du temps. */
  hint?: string;
  /** Page-contexte de la question. */
  page: number;
  /** Réponse envoyée à la correction — vide tant qu'on n'a pas répondu. */
  answer: string;
  /** Verdict et correction ; null tant que Gemma n'a pas corrigé. */
  feedback: QaFeedback | null;
}

interface Message {
  role: "user" | "assistant" | "system" | "qa";
  text: string;
  /** Renseigné pour `role === "qa"` : l'encadré de question. */
  qa?: QaRecord;
}

interface Highlight {
  quote?: string;
  text?: string;
  purpose?: "key" | "explain" | "reference";
}

/** Passage à cacher dans la page pendant un rappel libre. */
export interface QaMask {
  quote: string;
  placeholder?: string;
}

/** Pause proposée par Gemma (intervention `suggest_pause`), pas encore prise. */
interface Pause {
  message: string;
  minutes: number;
}

const MODES = ["discret", "normal", "coach"] as const;

// Disposition de la zone de discussion, mémorisée entre sessions.
type Layout = "float" | "dockRight";
type Rect = { x: number; y: number; width: number; height: number };
const DOCK_TOP = 56; // hauteur de la barre flottante du lecteur
// Cadence max. du signal « engaged » (miroir de settings.ATTENTION_ENGAGED_REPORT_S).
const ENGAGED_REPORT_MS = 10_000;
const LS_RECT = "gemma:panelRect";
const LS_LAYOUT = "gemma:layout";
const LS_DOCKW = "gemma:dockWidth";
const LS_BUBBLE = "gemma:bubblePos";

/** Ramène une position mémorisée dans la fenêtre courante.
 *
 *  Les positions sont écrites au pixel où on a lâché le panneau, dans la
 *  fenêtre d'alors. Rouvrir l'application plus petite — sortie du plein écran,
 *  écran externe débranché — replaçait la bulle au-delà du bord : invisible,
 *  et surtout hors du cadre du lecteur, qu'elle allongeait d'autant. */
function clampToWindow(rect: Rect): Rect {
  const margin = 12;
  return {
    ...rect,
    x: Math.min(Math.max(rect.x, margin), Math.max(margin, window.innerWidth - rect.width - margin)),
    y: Math.min(Math.max(rect.y, margin), Math.max(margin, window.innerHeight - rect.height - margin)),
  };
}

function loadRect(key: string, fallback: Rect): Rect {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const o = JSON.parse(raw);
      if (typeof o?.x === "number" && typeof o?.width === "number") return clampToWindow(o);
    }
  } catch {
    /* ignore */
  }
  return fallback;
}
function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore */
  }
}

export function GemmaPanel({
  docId,
  currentPage,
  sessionId,
  onHighlights,
  contextChips,
  onRemoveContextChip,
  onGatedChange,
  onMask,
  onZone,
  onGoToPage,
  pageCount,
  demo = false,
  reading = false,
  ended = false,
  paused = null,
  onPauseRequest,
  onDemoReady,
}: {
  docId: number;
  currentPage: number;
  sessionId?: number | null;
  onHighlights?: (items: Highlight[], page: number) => void;
  contextChips?: { id: number; page: number; text: string }[];
  onRemoveContextChip?: (id: number) => void;
  onGatedChange?: (active: boolean, page?: number) => void;
  /** Passage à cacher dans la page (rappel libre), null pour le redécouvrir. */
  onMask?: (mask: QaMask | null, page: number) => void;
  /**
   * Zone précise de la page visée par la question (citation), null quand la
   * carte se referme. Le lecteur la retrouve sur la page et la cadre entière.
   */
  onZone?: (quote: string | null, page: number) => void;
  /** Clic sur une référence de page (« p.29 ») dans une réponse : le lecteur y va. */
  onGoToPage?: (page: number) => void;
  /** Nombre de pages du document : borne les références cliquables. */
  pageCount?: number;
  /**
   * Séance de démonstration de la visite guidée : AUCUN WebSocket n'est ouvert
   * et le contenu affiché est écrit d'avance (`demoScript.ts`). C'est ce qui
   * garantit que la visite n'écrit rien et ne dépend pas d'Ollama.
   */
  demo?: boolean;
  /**
   * Le sas d'entrée est franchi : la lecture commence. Le WebSocket, lui, est
   * ouvert dès l'arrivée sur le document ; c'est ce signal, pas l'ouverture,
   * qui fait partir le warm-up avant la première question de Gemma.
   */
  reading?: boolean;
  /**
   * La session est terminée (« Terminer ») : le WebSocket se ferme tout de
   * suite, pendant que le sas de sortie recouvre le lecteur. Côté serveur, la
   * déconnexion coupe la génération en vol, arrête le ticker (plus
   * d'intervention enfilée, plus de dérive d'attention pendant que l'étudiant
   * écrit ses réflexions) et persiste le temps passé par page.
   */
  ended?: boolean;
  /**
   * La lecture est en pause (écran de pause du lecteur) : le serveur fige tout
   * — ni observation, ni intervention, ni horloge — et le panneau cesse
   * d'envoyer présence, gestes et page visible jusqu'à la reprise.
   */
  paused?: ReadingPause | null;
  /** « Faire une pause » sur la carte de Gemma : le lecteur ouvre l'écran de pause. */
  onPauseRequest?: (minutes: number) => void;
  /** Rend à la visite de quoi jouer les répliques, tant que le panneau vit. */
  onDemoReady?: (controls: { openPanel: () => void; play: (beat: DemoBeat) => void } | null) => void;
}) {
  const t = useT();
  // Gemma démarre fermé : l'utilisateur (ou une intervention) l'ouvre au besoin.
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [mode, setMode] = useState<(typeof MODES)[number]>("normal");
  // L'encadré de question en jeu (à répondre, puis à clore) ; les encadrés
  // eux-mêmes vivent dans `messages`, à leur place dans le fil.
  const [liveQaId, setLiveQaId] = useState<number | null>(null);
  const qaSeq = useRef(0);
  const [qaDraft, setQaDraft] = useState("");
  // Flashcards demandées depuis une réponse du fil, par index de message :
  // un « + Flashcard » ne part qu'une fois — ni pendant que la précédente se
  // crée, ni une fois créée. Le serveur refuse de toute façon le doublon,
  // mais le bouton ne doit pas non plus laisser croire qu'il le ferait.
  const [flashcardState, setFlashcardState] = useState<Record<number, "pending" | "done">>({});
  // Question automatique bloquante : verrouille le scroll du lecteur (cf. onGatedChange).
  const [gated, setGated] = useState(false);
  // Gemma inspecte la page (décide d'intervenir) -> la bulle se tourne vers le PDF.
  const [scanning, setScanning] = useState(false);
  // Pause recommandée : une carte qu'on peut prendre, pas une phrase de plus
  // dans le fil. La prendre ouvre l'écran de pause du lecteur (`onPauseRequest`).
  const [pause, setPause] = useState<Pause | null>(null);

  // Disposition / taille de la zone de discussion (libre + presets), persistées.
  const floatDefault: Rect = { x: Math.max(20, window.innerWidth - 640), y: Math.max(20, window.innerHeight - 560), width: 360, height: 480 };
  // Visite guidée : Gemma est ancrée à droite, point. Les sept étapes qui la
  // commentent désignent tour à tour son corps, son sélecteur de mode, ses
  // raccourcis et sa carte de question ; un panneau flottant, à une position
  // héritée d'une séance précédente et déplaçable d'un glissé, ferait sauter
  // ces découpes d'une étape à l'autre. Le réglage de l'utilisateur n'est pas
  // écrasé pour autant : en démonstration, on ne le relit ni ne l'écrit.
  const [layout, setLayout] = useState<Layout>(() =>
    demo ? "dockRight" : localStorage.getItem(LS_LAYOUT) === "dockRight" ? "dockRight" : "float",
  );
  const [floatRect, setFloatRect] = useState<Rect>(() => loadRect(LS_RECT, floatDefault));
  const [dockWidth, setDockWidth] = useState<number>(() => Number(localStorage.getItem(LS_DOCKW)) || 380);
  const [parentSize, setParentSize] = useState({ w: window.innerWidth, h: window.innerHeight });
  const panelRef = useRef<HTMLDivElement>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const pageRef = useRef(currentPage);
  pageRef.current = currentPage;
  const onHighlightsRef = useRef(onHighlights);
  onHighlightsRef.current = onHighlights;
  const onGatedChangeRef = useRef(onGatedChange);
  onGatedChangeRef.current = onGatedChange;
  const onMaskRef = useRef(onMask);
  onMaskRef.current = onMask;
  const onZoneRef = useRef(onZone);
  onZoneRef.current = onZone;
  const contextChipsRef = useRef(contextChips);
  contextChipsRef.current = contextChips;
  const gatedRef = useRef(false);
  gatedRef.current = gated;
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  // Page-contexte de la question bloquante : le lecteur y revient si la
  // réponse est fausse, après avoir été libéré le temps de la correction.
  const gatedPageRef = useRef<number | undefined>(undefined);
  // Miroirs de l'état Q&R pour les gestionnaires du socket (fermetures figées).
  const liveQaIdRef = useRef<number | null>(null);
  liveQaIdRef.current = liveQaId;
  const messagesRef = useRef<Message[]>([]);
  messagesRef.current = messages;
  const bodyRef = useRef<HTMLDivElement>(null);

  function setGatedState(active: boolean, page?: number) {
    setGated(active);
    if (active) gatedPageRef.current = page;
    onGatedChangeRef.current?.(active, page);
  }

  function applyMask(mask: QaMask | null) {
    onMaskRef.current?.(mask, pageRef.current);
  }

  /** L'encadré en jeu, s'il y en a un (lu depuis le miroir : les gestionnaires
   *  du socket vivent dans une fermeture figée). */
  function liveQa(): QaRecord | undefined {
    const id = liveQaIdRef.current;
    if (id === null) return undefined;
    return messagesRef.current.find((m) => m.qa?.id === id)?.qa;
  }

  function patchQa(id: number, patch: Partial<QaRecord>) {
    setMessages((m) => m.map((msg) => (msg.qa?.id === id ? { ...msg, qa: { ...msg.qa, ...patch } } : msg)));
  }

  /** Une nouvelle question entre dans le fil, à la suite, et devient celle en jeu.
   *  La précédente — répondue ou non — y reste telle quelle, en lecture seule. */
  /** Délégation : les liens `data-page-ref` sont injectés par renderMathToHtml. */
  function handlePageRefClick(e: ReactMouseEvent<HTMLDivElement>) {
    const target = (e.target as HTMLElement).closest<HTMLElement>("[data-page-ref]");
    if (!target) return;
    e.preventDefault();
    const page = Number(target.dataset.pageRef);
    if (Number.isFinite(page) && page >= 1) onGoToPage?.(page);
  }

  function openQa(record: Omit<QaRecord, "id" | "answer" | "feedback">) {
    const id = ++qaSeq.current;
    setMessages((m) => [...m, { role: "qa", text: record.question, qa: { ...record, id, answer: "", feedback: null } }]);
    setLiveQaId(id);
    liveQaIdRef.current = id;
    setQaDraft("");
  }

  /** Fin de partie pour l'encadré en jeu : il reste dans le fil, mais ne se
   *  joue plus (plus de champ, plus de boutons). */
  function endQa() {
    setLiveQaId(null);
    liveQaIdRef.current = null;
  }

  /**
   * Gemma a fini de réfléchir. Le lecteur avait été rendu le temps de la
   * réflexion : si une question bloquante est toujours en jeu, il revient se
   * caler sur sa zone ; s'il n'y a plus rien à répondre (la nouvelle question
   * n'est pas arrivée), le verrou n'a plus d'objet et tombe.
   */
  function restoreGate() {
    if (!gatedRef.current) return;
    if (liveQaIdRef.current !== null) onGatedChangeRef.current?.(true, gatedPageRef.current);
    else setGatedState(false);
  }

  /** Le lecteur est rendu le temps que Gemma réfléchit — on peut relire la
   *  page, défiler, zoomer. Le verrou, lui, reste armé (`gated`) : cf. restoreGate. */
  function releaseWhileThinking() {
    if (gatedRef.current) onGatedChangeRef.current?.(false);
  }

  function closeQa() {
    endQa();
    applyMask(null);
    onZoneRef.current?.(null, pageRef.current);
  }

  useEffect(() => {
    setMessages([{ role: "assistant", text: t("gemma.welcome") }]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Séance de démonstration : PAS de connexion. C'est la garantie centrale de
    // la visite — sans WebSocket, il n'y a ni jauges, ni questions enregistrées,
    // ni dérive d'attention, donc rien qui puisse atteindre le profil.
    if (demo) {
      setConnected(true);
      return;
    }
    // Session close : le nettoyage de l'effet précédent a fermé le socket, on
    // n'en rouvre pas — Gemma n'a plus rien à faire pour ce lecteur.
    if (ended) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/reader/${docId}/stream${wsTokenSuffix()}`);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (e) => {
      const evt = JSON.parse(e.data);
      if (evt.type === "scanning") {
        setScanning(!!evt.active);
        return;
      }
      if (evt.type === "answer") {
        setBusy(false);
        setMessages((m) => [...m, { role: "assistant", text: evt.answer || "(réponse vide)" }]);
        if (Array.isArray(evt.highlights) && evt.highlights.length) {
          onHighlightsRef.current?.(evt.highlights, pageRef.current);
        }
        restoreGate();
      } else if (evt.type === "error") {
        setBusy(false);
        setMessages((m) => [...m, { role: "assistant", text: `⚠️ ${evt.message || "Erreur"}` }]);
        restoreGate();
      } else if (evt.type === "intervention") {
        if (evt.kind === "suggest_pause") {
          setPause({
            message: evt.message || "",
            // La durée vient du serveur (config/settings.py), jamais de l'UI.
            minutes: Number(evt.pause_minutes) > 0 ? Number(evt.pause_minutes) : 5,
          });
          setOpen(true);
          return;
        }
        const text = [evt.message, evt.question].filter(Boolean).join("\n\n");
        if (text) {
          setOpen(true);
          setMessages((m) => [...m, { role: "assistant", text }]);
        }
        if (Array.isArray(evt.highlights) && evt.highlights.length) {
          onHighlightsRef.current?.(evt.highlights, pageRef.current);
        }
      } else if (evt.type === "system") {
        setMessages((m) => [...m, { role: "system", text: evt.message }]);
      } else if (evt.type === "qa_question" || evt.type === "gated_question") {
        setBusy(false);
        const page = Number(evt.page) > 0 ? Number(evt.page) : pageRef.current;
        // La question précédente, si elle était encore en jeu, reste dans le
        // fil telle quelle ; la nouvelle s'écrit à la suite.
        openQa({
          question: evt.question || "",
          choices: evt.choices ?? null,
          type: evt.question_type || "open",
          mask: evt.mask?.quote ? evt.mask : null,
          hint: evt.session_hint || "",
          page,
        });
        // Rappel libre : le passage disparaît de la page le temps de répondre.
        applyMask(evt.mask?.quote ? evt.mask : null);
        // Zone visée : le lecteur la cadre entière (et y reste, verrouillé ou non).
        onZoneRef.current?.(evt.zone?.quote || null, page);
        setOpen(true);
        // Question automatique : verrouille le scroll sur la page-contexte. Une
        // question de reprise (« Réessayer » après une réponse fausse) arrive
        // sans le drapeau mais prolonge le même blocage : le lecteur, rendu le
        // temps de la génération, revient se caler dessus.
        if (evt.type === "gated_question" || gatedRef.current) setGatedState(true, page);
      } else if (evt.type === "qa_feedback") {
        setBusy(false);
        if (liveQaIdRef.current !== null) {
          patchQa(liveQaIdRef.current, {
            feedback: { verdict: evt.verdict || "", feedback: evt.feedback || "", hint: evt.hint || "" },
          });
        }
        // La réponse est donnée : on rend le passage masqué.
        applyMask(null);
        if (Array.isArray(evt.highlights) && evt.highlights.length) {
          onHighlightsRef.current?.(evt.highlights, pageRef.current);
        }
        if (evt.flashcard_created) {
          setMessages((m) => [...m, { role: "system", text: t("gemma.fc_auto_created") }]);
        }
        if (gatedRef.current) {
          // Idée principale présente -> fin du verrouillage. Sinon, le lecteur
          // — libéré le temps de la correction — revient se caler sur la zone.
          if (evt.verdict === "correct" || evt.verdict === "partial") setGatedState(false);
          else onGatedChangeRef.current?.(true, gatedPageRef.current);
        }
        // Réponse juste : rien à reprendre, la lecture enchaîne sans passer par
        // « Terminer ». L'encadré reste dans le fil avec sa correction, en
        // lecture seule, et la zone cadrée est rendue au lecteur. Une réponse
        // partielle ou fausse garde ses boutons : il y a encore une suite à choisir.
        if (evt.verdict === "correct") closeQa();
      }
    };
    // Présence : fenêtre masquée ou application passée au second plan. C'est le
    // seul signal d'absence dont dispose la dérive passive d'attention côté
    // serveur — sans lui, `attention` ne mesurait que la performance aux questions.
    let away = false;
    const reportPresence = () => {
      // En pause, l'élève est parti : on ne l'observe plus (le serveur l'ignore aussi).
      if (pausedRef.current) return;
      const hidden = document.hidden || !document.hasFocus();
      if (hidden === away || ws.readyState !== WebSocket.OPEN) return;
      away = hidden;
      ws.send(JSON.stringify({ type: "activity", hidden }));
    };
    document.addEventListener("visibilitychange", reportPresence);
    window.addEventListener("blur", reportPresence);
    window.addEventListener("focus", reportPresence);
    // Engagement : défilement, souris, clavier. Rester longtemps sur une page
    // en la parcourant (deuxième colonne, retour sur un schéma) n'est pas du
    // décrochage ; sans ce signal, la dérive passive le comptait comme tel.
    // Compressé : au plus un message toutes les ENGAGED_REPORT_MS.
    let lastEngaged = 0;
    const reportEngaged = () => {
      if (pausedRef.current) return;
      const now = Date.now();
      if (now - lastEngaged < ENGAGED_REPORT_MS || ws.readyState !== WebSocket.OPEN) return;
      lastEngaged = now;
      ws.send(JSON.stringify({ type: "activity", hidden: false, engaged: true }));
    };
    const engagedEvents: (keyof WindowEventMap)[] = ["wheel", "scroll", "mousemove", "keydown", "pointerdown", "touchmove"];
    for (const ev of engagedEvents) window.addEventListener(ev, reportEngaged, { capture: true, passive: true });

    wsRef.current = ws;
    return () => {
      document.removeEventListener("visibilitychange", reportPresence);
      window.removeEventListener("blur", reportPresence);
      window.removeEventListener("focus", reportPresence);
      for (const ev of engagedEvents) window.removeEventListener(ev, reportEngaged, { capture: true });
      ws.close();
    };
  }, [docId, demo, ended]);

  useEffect(() => {
    const ws = wsRef.current;
    if (pausedRef.current) return;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "viewport", page: currentPage, session_id: sessionId ?? null }));
  }, [currentPage, sessionId]);

  // Pause de la lecture : un message à l'arrêt, un à la reprise. Le serveur
  // mesure la durée et ce qui l'a précédée (services/pause.py) ; ici on ne fait
  // que signaler. Socket fermé (séance terminée pendant la pause) : rien ne
  // part, le serveur enregistre la pause à la déconnexion.
  const pauseSentRef = useRef(false);
  useEffect(() => {
    const ws = wsRef.current;
    const live = !demo && ws !== null && ws.readyState === WebSocket.OPEN;
    if (paused && !pauseSentRef.current) {
      pauseSentRef.current = true;
      if (live) ws.send(JSON.stringify({ type: "pause", source: paused.source, minutes: paused.plannedMin }));
    } else if (!paused && pauseSentRef.current) {
      pauseSentRef.current = false;
      if (live) ws.send(JSON.stringify({ type: "resume" }));
      setMessages((m) => [...m, { role: "system", text: t("gemma.pause_over") }]);
    }
  }, [paused, demo, t]);

  // Entrée dans la lecture : le serveur démarre le warm-up de la première
  // question. `connected` couvre le socket pas encore ouvert à la sortie du sas ;
  // un envoi répété est sans effet côté serveur.
  useEffect(() => {
    const ws = wsRef.current;
    if (reading && connected && ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "start_reading" }));
  }, [reading, connected]);

  // ── La séance de démonstration ──────────────────────────────────────────
  //
  // Les répliques ne se déroulent pas toutes seules : la visite les déclenche,
  // une par étape, pour que la bulle qui les explique soit déjà à l'écran quand
  // elles arrivent. Rien ici ne part sur le réseau.
  const playDemo = useCallback(
    (beat: DemoBeat) => {
      if (beat === "question") {
        openQa({
          question: t(DEMO_QUESTION.questionKey),
          choices: DEMO_QUESTION.choiceKeys.map((key) => t(key)),
          type: DEMO_QUESTION.type,
          mask: null,
          page: pageRef.current,
        });
        setOpen(true);
        return;
      }
      const { userKey, assistantKey } = DEMO_BEATS[beat];
      setOpen(true);
      if (userKey) setMessages((m) => [...m, { role: "user", text: t(userKey) }]);
      if (!assistantKey) return;
      // Un temps de réflexion simulé : sans lui, la réponse apparaît d'un bloc
      // en même temps que la question, et on ne comprend pas qui dit quoi.
      setBusy(true);
      window.setTimeout(() => {
        setBusy(false);
        setMessages((m) => [...m, { role: "assistant", text: t(assistantKey) }]);
        // Les surlignages, eux, sont VRAIS : ils passent par la recherche PDFium
        // du lecteur. S'ils ne trouvent pas leur phrase dans le PDF, il ne se
        // passe rien de visible et la visite continue.
        onHighlightsRef.current?.(
          [
            { quote: DEMO_QUOTES.key, purpose: "key" },
            { quote: DEMO_QUOTES.explain, purpose: "explain" },
          ],
          pageRef.current,
        );
      }, DEMO_THINKING_MS);
    },
    [t],
  );

  // La visite ne peut piloter le panneau que tant qu'il est monté.
  useEffect(() => {
    if (!demo) return;
    onDemoReady?.({ openPanel: () => setOpen(true), play: playDemo });
    return () => onDemoReady?.(null);
    // `onDemoReady` est stable (useCallback côté Reader) ; le relire à chaque
    // rendu rebrancherait les contrôles en boucle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demo, playDemo]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  // Mesure la zone parente (conteneur du lecteur = parent du wrapper react-rnd,
  // celui que `bounds="parent"` contraint) pour ancrer la disposition « à droite ».
  useLayoutEffect(() => {
    const measure = () => {
      const container = panelRef.current?.parentElement?.parentElement as HTMLElement | null;
      if (container && container.clientHeight > 0) setParentSize({ w: container.clientWidth, h: container.clientHeight });
      else setParentSize({ w: window.innerWidth, h: window.innerHeight });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [open, layout]);

  useEffect(() => {
    if (!demo) save(LS_LAYOUT, layout);
  }, [layout, demo]);

  // Géométrie courante du panneau selon la disposition choisie.
  const dockRect: Rect = { x: Math.max(0, parentSize.w - dockWidth), y: DOCK_TOP, width: dockWidth, height: Math.max(240, parentSize.h - DOCK_TOP - 12) };
  const rect: Rect = layout === "dockRight" ? dockRect : floatRect;

  function applyFloatRect(next: Rect) {
    setFloatRect(next);
    save(LS_RECT, next);
  }
  function applyDockWidth(w: number) {
    const clamped = Math.max(300, Math.min(720, Math.round(w)));
    setDockWidth(clamped);
    save(LS_DOCKW, clamped);
  }

  function sendRaw(payload: object): boolean {
    // Séance de démonstration : rien ne part. Les commandes restent cliquables
    // — c'est la moitié de ce que la visite montre — mais elles n'atteignent
    // aucun serveur, et surtout pas « Gemma est indisponible », qui serait faux
    // et alarmant au premier lancement.
    if (demo) return false;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setMessages((m) => [...m, { role: "assistant", text: t("gemma.unavailable") }]);
      return false;
    }
    ws.send(JSON.stringify(payload));
    return true;
  }

  function ask() {
    const text = draft.trim();
    if (!text || busy) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setDraft("");
    setBusy(true);
    const snippets = (contextChipsRef.current ?? []).map((c) => c.text);
    // Message non parti : on rend la main. Sans ça, l'indicateur « Gemma
    // réfléchit… » tournait indéfiniment sur une connexion fermée.
    if (!sendRaw({ type: "ask", question: text, page: pageRef.current, selected_snippets: snippets })) {
      setBusy(false);
      return;
    }
    releaseWhileThinking();
  }

  function action(type: "rephrase" | "recap" | "hook", label: string) {
    if (busy) return;
    setMessages((m) => [...m, { role: "user", text: label }]);
    setBusy(true);
    if (!sendRaw({ type, page: pageRef.current })) {
      setBusy(false);
      return;
    }
    releaseWhileThinking();
  }

  function changeMode(m: (typeof MODES)[number]) {
    setMode(m);
    sendRaw({ type: "mode", mode: m });
  }

  function startQa() {
    if (busy) return;
    // Séance de démonstration : « Quiz-moi » rejoue la question écrite d'avance
    // plutôt que d'en demander une. C'est ce que la visite annonce — on montre
    // le geste, on ne fait pas tourner l'évaluateur.
    if (demo) {
      playDemo("question");
      return;
    }
    // « Nouvelle question » / « Réessayer » : la précédente et sa correction
    // restent dans le fil, en lecture seule ; la suivante viendra à la suite.
    endQa();
    setBusy(true);
    if (!sendRaw({ type: "start_qa", page: pageRef.current, session_id: sessionId ?? null })) {
      setBusy(false);
      restoreGate();
      return;
    }
    // Même après une réponse fausse : le temps que Gemma prépare la question
    // suivante, on est libre de bouger dans le document.
    releaseWhileThinking();
  }

  /** La carte de Gemma est acceptée : le lecteur ouvre SON écran de pause, le
   *  même que celui du bouton — une seule pause, un seul chemin vers le serveur. */
  function acceptPause() {
    if (!pause) return;
    onPauseRequest?.(pause.minutes);
    setPause(null);
  }

  function submitQa(answer: string) {
    const qa = liveQa();
    if (busy || !answer.trim() || !qa) return;
    // C'est la réponse envoyée qui reste dans l'encadré, pas le brouillon
    // (vide pour un QCM ou une remise en ordre).
    patchQa(qa.id, { answer });
    if (demo) {
      // Verdict écrit d'avance : aucune réponse n'est évaluée, donc rien n'est
      // enregistré ni compté dans la rétention du profil.
      patchQa(qa.id, { feedback: { verdict: DEMO_QUESTION.verdict, feedback: t(DEMO_QUESTION.feedbackKey) } });
      return;
    }
    setBusy(true);
    if (!sendRaw({ type: "qa_answer", question: qa.question, answer, page: pageRef.current, session_id: sessionId ?? null })) {
      setBusy(false);
      return;
    }
    // Le temps que Gemma corrige, le lecteur est rendu. Le verrou, lui, reste
    // armé — si la réponse est fausse, le lecteur revient se caler sur la zone.
    releaseWhileThinking();
  }

  async function makeFlashcard(index: number) {
    // Un seul départ par réponse : le second clic — pendant la création ou
    // après — ne fait rien. Le serveur reconnaît de toute façon l'échange déjà
    // transformé, mais l'appel LLM serait parti pour rien.
    if (flashcardState[index]) return;
    setFlashcardState((s) => ({ ...s, [index]: "pending" }));
    let front = t("gemma.note_front");
    for (let i = index - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        front = messages[i].text;
        break;
      }
    }
    try {
      // Flashcard intelligente : le LLM réécrit recto/verso en carte autoportante.
      const { created } = await api.createFlashcardFromExchange(front, messages[index].text, docId, pageRef.current);
      setFlashcardState((s) => ({ ...s, [index]: "done" }));
      setMessages((m) => [...m, { role: "system", text: t(created ? "gemma.fc_created" : "gemma.fc_exists") }]);
    } catch {
      setFlashcardState((s) => {
        const next = { ...s };
        delete next[index];
        return next;
      });
      setMessages((m) => [...m, { role: "system", text: t("gemma.fc_failed") }]);
    }
  }

  if (!open) {
    return <GemmaBubble scanning={scanning} onOpen={() => setOpen(true)} title={t("gemma.open")} fixed={demo} />;
  }

  return (
    <Rnd
      size={{ width: rect.width, height: rect.height }}
      position={{ x: rect.x, y: rect.y }}
      minWidth={300}
      minHeight={layout === "dockRight" ? 240 : 320}
      bounds="parent"
      // Rien ne bouge pendant la visite : ni déplacement, ni redimensionnement.
      enableResizing={!demo}
      disableDragging={demo || layout === "dockRight"}
      dragHandleClassName="gemma-drag"
      // Les contrôles vivent DANS la poignée de déplacement : sans ce `cancel`, cliquer
      // le sélecteur de mode arme un déplacement, et la liste native avale le mouseup
      // qui devait le terminer -> le panneau reste collé à la souris.
      cancel=".gemma-nodrag"
      onDragStop={(_e, d) => {
        if (layout === "float") applyFloatRect({ ...floatRect, x: d.x, y: d.y });
      }}
      onResizeStop={(_e, _dir, refEl, _delta, position) => {
        const w = parseFloat(refEl.style.width);
        const h = parseFloat(refEl.style.height);
        if (layout === "dockRight") applyDockWidth(w);
        else applyFloatRect({ x: position.x, y: position.y, width: w, height: h });
      }}
      style={{ zIndex: 50 }}
    >
      <div ref={panelRef} style={panelStyle}>
        <div className="gemma-drag" style={{ ...headerStyle, cursor: layout === "dockRight" ? "default" : "move" }}>
          <strong className="flex items-center gap-1.5 text-sm text-accent-foreground">
            <Sparkles className="size-4" aria-hidden />
            Gemma
            {/* Le voyant était 🟢/⚪️ : deux emoji dont le rendu change d'un OS à
                l'autre, et dont personne ne devine le sens. Une pastille + une
                infobulle disent la même chose, en toutes lettres au survol. */}
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  role="status"
                  aria-label={connected ? t("gemma.connected") : t("gemma.disconnected")}
                  className={cn(
                    "size-2 rounded-full transition-colors duration-normal ease-brand",
                    connected ? "bg-success" : "bg-muted-light",
                  )}
                />
              </TooltipTrigger>
              <TooltipContent>
                {connected ? t("gemma.connected") : t("gemma.disconnected")}
              </TooltipContent>
            </Tooltip>
          </strong>
          <div className="gemma-nodrag" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {/* Le <select> natif affichait « discret / normal / coach » bruts, non
                traduits, et non stylables. Chaque mode explique maintenant ce
                qu'il change — mais seulement pendant le choix : `SelectValue`
                recopierait sinon l'explication dans le bouton fermé, qui
                mangeait la moitié de l'en-tête. Ses enfants explicites
                réduisent le bouton au seul nom du mode. */}
            <Select value={mode} onValueChange={(v) => changeMode(v as (typeof MODES)[number])}>
              <SelectTrigger
                size="sm"
                data-tour="gemma-mode"
                aria-label={t("gemma.mode_label")}
                className="h-7 w-auto gap-1 border-border bg-surface text-[11px]"
              >
                <SelectValue>{t(`gemma.mode_${mode}`)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {MODES.map((m) => (
                  <SelectItem key={m} value={m} className="text-xs">
                    <span className="flex flex-col">
                      <span className="font-semibold">{t(`gemma.mode_${m}`)}</span>
                      <span className="text-[11px] text-muted-foreground">
                        {t(`gemma.mode_${m}_hint`)}
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("gemma.focus")}
                  onClick={() => sendRaw({ type: "focus" })}
                >
                  <Target className="size-4" aria-hidden />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("gemma.focus")}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={layout === "dockRight" ? t("gemma.float") : t("gemma.dock_right")}
                  onClick={() => setLayout(layout === "dockRight" ? "float" : "dockRight")}
                  className={layout === "dockRight" ? "text-brand-ink" : undefined}
                >
                  {layout === "dockRight" ? (
                    <Maximize2 className="size-4" aria-hidden />
                  ) : (
                    <PanelRight className="size-4" aria-hidden />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {layout === "dockRight" ? t("gemma.float") : t("gemma.dock_right")}
              </TooltipContent>
            </Tooltip>
            {!gated && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("common.close")}
                onClick={() => setOpen(false)}
              >
                <X className="size-4" aria-hidden />
              </Button>
            )}
          </div>
        </div>

        {/* Le fil de conversation : trois étapes de la visite s'y ancrent (la
            découverte du panneau, la réponse à une question, l'intervention
            autonome). Une seule ancre pour les trois — c'est bien le même
            endroit qu'on désigne à chaque fois. */}
        <div ref={bodyRef} data-tour="gemma-body" data-testid="gemma-body" style={bodyStyle}>
          {messages.map((m, i) =>
            m.role === "system" ? (
              <div key={i} style={{ alignSelf: "center", fontSize: 11, color: "var(--muted)", fontStyle: "italic" }}>
                {m.text}
              </div>
            ) : m.role === "qa" && m.qa ? (
              // L'encadré en jeu porte l'ancre de la visite ; les autres sont
              // des traces, à leur place dans le fil.
              <div key={`qa-${m.qa.id}`} data-tour={m.qa.id === liveQaId ? "gemma-qa" : undefined} style={{ alignSelf: "stretch" }}>
                <QaCard
                  record={m.qa}
                  live={m.qa.id === liveQaId}
                  draft={qaDraft}
                  setDraft={setQaDraft}
                  busy={busy}
                  locked={gated}
                  onSubmit={submitQa}
                  onNext={startQa}
                  onClose={closeQa}
                />
              </div>
            ) : (
              <div key={i} data-role={m.role} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "88%" }}>
                <div
                  style={bubble(m.role === "user" ? "user" : "assistant")}
                  onClick={m.role === "assistant" ? handlePageRefClick : undefined}
                  {...(m.role === "assistant"
                    ? { dangerouslySetInnerHTML: { __html: renderMathToHtml(m.text, { pageLinks: true, maxPage: pageCount }) } }
                    : { children: m.text })}
                />
                {m.role === "assistant" && i > 0 && (
                  <button
                    onClick={() => makeFlashcard(i)}
                    disabled={Boolean(flashcardState[i])}
                    aria-disabled={Boolean(flashcardState[i])}
                    title={t("gemma.flashcard_hint")}
                    className="mt-1 rounded-[4px] border-none bg-transparent p-0 text-[11px] text-brand-ink
                               underline-offset-2 transition-colors duration-fast ease-brand
                               hover:text-accent-foreground hover:underline
                               disabled:cursor-default disabled:text-muted-foreground disabled:no-underline
                               focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                  >
                    {flashcardState[i] === "pending"
                      ? t("gemma.fc_pending")
                      : flashcardState[i] === "done"
                        ? t("gemma.fc_done")
                        : t("gemma.flashcard")}
                  </button>
                )}
              </div>
            ),
          )}
          {pause && <PauseCard pause={pause} onStart={acceptPause} onDismiss={() => setPause(null)} />}
          {busy && (
            <div
              role="status"
              aria-live="polite"
              className="flex items-center gap-2 self-start text-xs text-muted-foreground"
            >
              {/* Le texte italique « Gemma réfléchit… » était immobile : rien ne
                  distinguait une attente en cours d'une interface figée. */}
              <span className="flex gap-1" aria-hidden>
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="size-1.5 animate-bounce rounded-full bg-muted-light"
                    style={{ animationDelay: `${i * 140}ms`, animationDuration: "900ms" }}
                  />
                ))}
              </span>
              {t("gemma.thinking")}
            </div>
          )}
        </div>

        <div data-tour="gemma-chips" style={{ display: "flex", gap: 6, padding: "6px 10px", flexWrap: "wrap", borderTop: "1px solid var(--border)" }}>
          <Button variant="chip" size="sm" disabled={busy} onClick={() => action("rephrase", t("gemma.rephrase_cmd"))}>
            {t("gemma.rephrase")}
          </Button>
          <Button variant="chip" size="sm" disabled={busy} onClick={() => action("recap", t("gemma.recap_cmd"))}>
            {t("gemma.recap")}
          </Button>
          <Button variant="chip" size="sm" disabled={busy} onClick={() => action("hook", t("gemma.curiosity_cmd"))}>
            {t("gemma.curiosity")}
          </Button>
          <Button
            variant="chip"
            size="sm"
            disabled={busy}
            onClick={startQa}
            className="border-brand text-accent-foreground"
          >
            {t("gemma.quizme")}
          </Button>
        </div>

        {contextChips && contextChips.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "6px 10px", borderTop: "1px solid var(--border)" }}>
            {contextChips.map((c) => (
              <span key={c.id} style={contextChipStyle} title={c.text}>
                <span style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {t("gemma.context_chip", { n: c.page })} · {c.text}
                </span>
                <button onClick={() => onRemoveContextChip?.(c.id)} style={chipClose} title={t("gemma.context_remove")}>
                  ✕
                </button>
              </span>
            ))}
          </div>
        )}

        <div style={{ display: "flex", alignItems: "flex-end", gap: 8, padding: 10, borderTop: "1px solid var(--border)" }}>
          <AutoGrowTextarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onSubmit={ask}
            placeholder={t("gemma.placeholder", { n: currentPage })}
            style={inputStyle}
          />
          <Button
            onClick={ask}
            pending={busy}
            aria-label={t("gemma.send")}
            size="icon"
            className="shrink-0"
          >
            {!busy && <CornerDownLeft className="size-4" aria-hidden />}
          </Button>
        </div>
      </div>
    </Rnd>
  );
}

// Fond translucide : on voit le PDF à travers la zone de discussion.
const panelStyle: React.CSSProperties = {
  display: "flex", flexDirection: "column", height: "100%",
  background: "color-mix(in srgb, var(--surface) 62%, transparent)",
  backdropFilter: "blur(12px) saturate(1.1)", WebkitBackdropFilter: "blur(12px) saturate(1.1)",
  border: "1px solid var(--border)", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-lg)", overflow: "hidden",
};
const headerStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px",
  background: "color-mix(in srgb, var(--accent-soft) 75%, transparent)", cursor: "move", userSelect: "none",
};
const bodyStyle: React.CSSProperties = { flex: 1, overflow: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 8 };
// Champ de saisie : passé à AutoGrowTextarea, qui attend un objet de style.
const inputStyle: React.CSSProperties = {
  flex: 1, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "8px 10px",
  background: "var(--bg)", color: "var(--text)", fontSize: 13,
};
const chip: React.CSSProperties = {
  border: "1px solid var(--border)", background: "var(--surface-soft)", color: "var(--text-soft)",
  borderRadius: 999, padding: "4px 10px", fontSize: 12, cursor: "pointer",
};
// L'encadré de question. En jeu : bord à l'accent, fond de surface. Joué :
// le même encadré, en plus discret (bord gauche seulement, fond adouci), pour
// qu'on distingue d'un coup d'œil ce qui est à jouer de ce qui a été joué.
const qaLiveStyle: React.CSSProperties = {
  display: "flex", flexDirection: "column", gap: 8, padding: 12,
  border: "1px solid var(--accent)", borderRadius: "var(--radius-md)", background: "var(--surface)",
};
const qaRecordStyle: React.CSSProperties = {
  display: "flex", flexDirection: "column", gap: 8, padding: "10px 12px",
  borderLeft: "3px solid var(--accent)", borderRadius: "var(--radius-md)", background: "var(--surface-soft)",
};
const pauseCardStyle: React.CSSProperties = {
  alignSelf: "stretch", display: "flex", flexDirection: "column", gap: 8, padding: 12,
  border: "1px solid var(--accent)", borderRadius: "var(--radius-md)", background: "var(--accent-soft)",
};
const contextChipStyle: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, maxWidth: "100%",
  background: "var(--accent-soft)", color: "var(--accent-ink)", border: "1px solid var(--border)",
  borderRadius: 999, padding: "3px 8px", fontSize: 11,
};
const chipClose: React.CSSProperties = {
  border: "none", background: "transparent", color: "var(--accent-ink)", cursor: "pointer", fontSize: 11, padding: 0, lineHeight: 1,
};

// ── Bulle Gemma : sphère 3D à deux yeux mobiles, déplaçable. ────────────────────
// Au repos, les pupilles suivent le curseur. Pendant que Gemma inspecte la page
// (`scanning`), la bulle se tourne vers le PDF et fixe son regard de ce côté.
function GemmaBubble({
  scanning,
  onOpen,
  title,
  fixed = false,
}: {
  scanning: boolean;
  onOpen: () => void;
  title: string;
  /** Visite guidée : toujours le même coin, et pas déplaçable. */
  fixed?: boolean;
}) {
  const SIZE = 64;
  const sphereRef = useRef<HTMLButtonElement>(null);
  const movedRef = useRef(false);
  const [pupil, setPupil] = useState({ x: 0, y: 0 });

  const start: Rect = { ...loadRect(LS_BUBBLE, { x: 0, y: 0, width: SIZE, height: SIZE }) };
  const corner = { x: Math.max(12, window.innerWidth - SIZE - 26), y: Math.max(12, window.innerHeight - SIZE - 26) };
  // La position mémorisée est ignorée pendant la visite : l'étape qui présente
  // la bulle doit la trouver au même endroit chez tout le monde.
  const defaultPos = fixed || !(start.x || start.y) ? corner : { x: start.x, y: start.y };

  // Suivi du curseur (désactivé en scanning : le regard est épinglé vers le PDF).
  useEffect(() => {
    if (scanning) return;
    const onMove = (e: MouseEvent) => {
      const el = sphereRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const ang = Math.atan2(e.clientY - (r.top + r.height / 2), e.clientX - (r.left + r.width / 2));
      const reach = 3.2;
      setPupil({ x: Math.cos(ang) * reach, y: Math.sin(ang) * reach });
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [scanning]);

  // En scanning : pupilles vers le PDF (gauche), sinon suivi du curseur.
  const look = scanning ? { x: -3.4, y: 0.6 } : pupil;

  return (
    <Rnd
      default={{ x: defaultPos.x, y: defaultPos.y, width: SIZE, height: SIZE }}
      enableResizing={false}
      disableDragging={fixed}
      bounds="parent"
      onDragStart={() => { movedRef.current = false; }}
      onDrag={() => { movedRef.current = true; }}
      onDragStop={(_e, d) => save(LS_BUBBLE, { x: d.x, y: d.y, width: SIZE, height: SIZE })}
      style={{ zIndex: 50 }}
    >
      <style>{BUBBLE_KEYFRAMES}</style>
      <div
        data-tour="gemma"
        style={{ width: SIZE, height: SIZE, perspective: 320, animation: "gemmaFloat 4.2s ease-in-out infinite" }}
      >
        {/* C'était un <div onClick> : la seule façon d'ouvrir Gemma était un clic
            souris — pas de tabulation, pas d'Entrée, rien d'annoncé. Un vrai
            <button> rend l'assistant atteignable au clavier, et `movedRef`
            continue de distinguer un clic d'une fin de glissement. */}
        <button
          ref={sphereRef}
          type="button"
          title={title}
          aria-label={title}
          onClick={() => { if (!movedRef.current) onOpen(); }}
          className="border-none p-0 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
          style={{ ...sphereStyle, transform: scanning ? "rotateY(-32deg) scale(1.04)" : "rotateY(0deg) scale(1)" }}
        >
          <div style={{ display: "flex", gap: 9, transform: "translateZ(10px)" }}>
            <Eye look={look} />
            <Eye look={look} />
          </div>
        </button>
      </div>
    </Rnd>
  );
}

function Eye({ look }: { look: { x: number; y: number } }) {
  return (
    <div style={eyeWhiteStyle}>
      <div style={{ ...pupilStyle, transform: `translate(${look.x}px, ${look.y}px)` }} />
    </div>
  );
}

const BUBBLE_KEYFRAMES = `
@keyframes gemmaFloat { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
`;
const sphereStyle: React.CSSProperties = {
  width: "100%", height: "100%", borderRadius: "50%", position: "relative", cursor: "pointer",
  display: "grid", placeItems: "center",
  background:
    "radial-gradient(circle at 34% 26%, rgba(255,255,255,0.85), rgba(255,255,255,0) 34%)," +
    "radial-gradient(circle at 68% 74%, var(--accent-hover), var(--accent) 52%, color-mix(in srgb, var(--accent) 55%, #000) 100%)",
  boxShadow:
    "0 12px 24px -8px rgba(0,0,0,0.45), inset -6px -8px 14px rgba(0,0,0,0.30), inset 6px 8px 16px rgba(255,255,255,0.35)",
  transformStyle: "preserve-3d",
  transition: "transform 0.5s cubic-bezier(0.2,0.8,0.2,1)",
};
// Le blanc de l'œil reste un blanc littéral, et NON `var(--on-accent)` : c'est
// un trait du personnage, pas du texte posé sur l'accent. En sombre `--on-accent`
// vaut une encre presque noire — Gemma s'y retrouverait avec des yeux noirs.
const eyeWhiteStyle: React.CSSProperties = {
  width: 17, height: 17, borderRadius: "50%", background: "#fff",
  display: "grid", placeItems: "center", boxShadow: "inset 0 1px 2px rgba(0,0,0,0.25)",
};
const pupilStyle: React.CSSProperties = {
  width: 7.5, height: 7.5, borderRadius: "50%", background: "#1b1b2b", transition: "transform 0.12s ease-out",
};

/** Pause recommandée : une carte qu'on peut PRENDRE.
 *
 *  `suggest_pause` existait de bout en bout côté serveur et se rendait comme
 *  une phrase de plus dans le fil : rien ne la distinguait, rien ne la
 *  déclenchait. La prendre ouvre l'écran de pause du lecteur, qui tient le
 *  décompte de la durée conseillée (features/session/PauseSas.tsx). */
function PauseCard({
  pause,
  onStart,
  onDismiss,
}: {
  pause: Pause;
  onStart: () => void;
  onDismiss: () => void;
}) {
  const t = useT();
  return (
    <div style={pauseCardStyle} role="group" aria-label={t("gemma.pause_title")}>
      <div
        className="flex items-center gap-1.5 text-[11px] font-bold tracking-wide uppercase"
        style={{ color: "var(--accent-ink)" }}
      >
        <Coffee className="size-3.5" aria-hidden />
        {t("gemma.pause_title")}
      </div>

      {pause.message && <div style={{ fontSize: 13, color: "var(--text)" }}>{pause.message}</div>}

      <div className="text-xs text-muted-foreground">{t("gemma.pause_note")}</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button onClick={onStart} style={{ ...chip, borderColor: "var(--accent)", color: "var(--accent-ink)" }}>
          {t("gemma.pause_start", { n: pause.minutes })}
        </button>
        <button onClick={onDismiss} style={chip}>
          {t("gemma.pause_decline")}
        </button>
      </div>
    </div>
  );
}

/**
 * L'encadré d'une question, en jeu ou joué — le même, pour qu'il ne bouge pas
 * de place ni d'aspect entre les deux : on répond dedans, on y lit la
 * correction, et il reste là, à sa place dans le fil, quand on continue.
 */
function QaCard({
  record,
  live,
  draft,
  setDraft,
  busy,
  locked = false,
  onSubmit,
  onNext,
  onClose,
}: {
  record: QaRecord;
  /** En jeu : champ de réponse, puis boutons de suite. Sinon lecture seule. */
  live: boolean;
  draft: string;
  setDraft: (v: string) => void;
  busy: boolean;
  locked?: boolean;
  onSubmit: (answer: string) => void;
  onNext: () => void;
  onClose: () => void;
}) {
  const t = useT();
  const { feedback } = record;
  // Verrouillé + réponse fausse : seule issue = une nouvelle question (pas de sortie).
  const stayLocked = live && locked && feedback?.verdict === "incorrect";
  return (
    <div style={live ? qaLiveStyle : qaRecordStyle} data-testid="qa-card" data-live={live || undefined}>
      <div className="flex flex-wrap items-center gap-2">
        <span style={{ fontSize: 11, fontWeight: 700, color: "var(--accent-ink)", letterSpacing: 0.4 }}>{t("flash.q")}</span>
        <QuestionTypeBadge type={record.type} />
      </div>
      <QuestionStem
        question={record.question}
        type={record.type}
        masked={live && !feedback && Boolean(record.mask)}
        showHint={live && !feedback}
      />

      {/* Conseil de régulation de séance (`session_hint`) : renseigné par le
          modèle quand l'attention passe sous son seuil, et rempli aussi par le
          repli hors ligne. Vide la plupart du temps. */}
      {live && record.hint && (
        <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Coffee className="mt-px size-3.5 shrink-0 text-brand-ink" aria-hidden />
          <span>
            <span className="sr-only">{t("gemma.hint_label")} : </span>
            {record.hint}
          </span>
        </div>
      )}

      {live && !feedback && (
        <AnswerInput
          // Une nouvelle question doit repartir d'un widget vierge (étapes
          // remélangées, ordre remis à zéro) : la question sert de clé.
          key={record.id}
          type={record.type}
          choices={record.choices}
          seed={record.question}
          draft={draft}
          setDraft={setDraft}
          busy={busy}
          onSubmit={onSubmit}
        />
      )}

      {record.answer && (feedback || !live) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 11, color: "var(--muted)" }}>{t("gemma.answer_given")}</span>
          <div
            style={{ ...bubble("user"), alignSelf: "flex-start", maxWidth: "100%" }}
            dangerouslySetInnerHTML={{ __html: renderMathToHtml(record.answer) }}
          />
        </div>
      )}

      {feedback && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <VerdictBadge verdict={feedback.verdict} />
          {/* La correction cite les formules du passage ($\alpha$…) comme
              l'énoncé : même rendu KaTeX, sinon le LaTeX s'affiche brut. */}
          {feedback.feedback && (
            <div
              style={{ fontSize: 13, color: "var(--text-soft)" }}
              dangerouslySetInnerHTML={{ __html: renderMathToHtml(feedback.feedback) }}
            />
          )}
          {live && feedback.hint && feedback.verdict === "incorrect" && (
            <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Lightbulb className="mt-px size-3.5 shrink-0 text-warning" aria-hidden />
              <span dangerouslySetInnerHTML={{ __html: renderMathToHtml(feedback.hint) }} />
            </div>
          )}
          {live && (
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={onNext} disabled={busy} style={{ ...chip, borderColor: "var(--accent)", color: "var(--accent-ink)" }}>
                {stayLocked ? t("gemma.retry_question") : t("gemma.new_question")}
              </button>
              {!stayLocked && (
                <button onClick={onClose} style={chip}>
                  {t("gemma.finish")}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function bubble(role: "user" | "assistant"): React.CSSProperties {
  return {
    padding: "8px 12px", borderRadius: 14, fontSize: 13, lineHeight: 1.45, whiteSpace: "pre-wrap",
    background: role === "user" ? "var(--accent-soft)" : "var(--surface-soft)",
    color: role === "user" ? "var(--accent-hover)" : "var(--text)", border: "1px solid var(--border)",
  };
}
