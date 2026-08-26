import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
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
import { AnswerInput } from "../questions/AnswerInput";
import { QuestionStem } from "../questions/QuestionStem";
import { QuestionTypeBadge } from "../questions/QuestionTypeBadge";
import { VerdictBadge } from "../questions/VerdictBadge";
import { renderMathToHtml } from "./renderMath";

interface Message {
  role: "user" | "assistant" | "system";
  text: string;
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

interface Qa {
  question: string;
  choices: string[] | null;
  type: string;
  mask: QaMask | null;
}

const MODES = ["discret", "normal", "coach"] as const;

// Disposition de la zone de discussion, mémorisée entre sessions.
type Layout = "float" | "dockRight";
type Rect = { x: number; y: number; width: number; height: number };
const DOCK_TOP = 56; // hauteur de la barre flottante du lecteur
const LS_RECT = "gemma:panelRect";
const LS_LAYOUT = "gemma:layout";
const LS_DOCKW = "gemma:dockWidth";
const LS_BUBBLE = "gemma:bubblePos";

function loadRect(key: string, fallback: Rect): Rect {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const o = JSON.parse(raw);
      if (typeof o?.x === "number" && typeof o?.width === "number") return o;
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
}) {
  const t = useT();
  // Gemma démarre fermé : l'utilisateur (ou une intervention) l'ouvre au besoin.
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [mode, setMode] = useState<(typeof MODES)[number]>("normal");
  const [qa, setQa] = useState<Qa | null>(null);
  const [qaFeedback, setQaFeedback] = useState<{ verdict: string; feedback: string; hint?: string } | null>(null);
  const [qaDraft, setQaDraft] = useState("");
  // Question automatique bloquante : verrouille le scroll du lecteur (cf. onGatedChange).
  const [gated, setGated] = useState(false);
  // Gemma inspecte la page (décide d'intervenir) -> la bulle se tourne vers le PDF.
  const [scanning, setScanning] = useState(false);

  // Disposition / taille de la zone de discussion (libre + presets), persistées.
  const floatDefault: Rect = { x: Math.max(20, window.innerWidth - 640), y: Math.max(20, window.innerHeight - 560), width: 360, height: 480 };
  const [layout, setLayout] = useState<Layout>(() => (localStorage.getItem(LS_LAYOUT) === "dockRight" ? "dockRight" : "float"));
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
  const contextChipsRef = useRef(contextChips);
  contextChipsRef.current = contextChips;
  const gatedRef = useRef(false);
  gatedRef.current = gated;
  const bodyRef = useRef<HTMLDivElement>(null);

  function setGatedState(active: boolean, page?: number) {
    setGated(active);
    onGatedChangeRef.current?.(active, page);
  }

  function applyMask(mask: QaMask | null) {
    onMaskRef.current?.(mask, pageRef.current);
  }

  useEffect(() => {
    setMessages([{ role: "assistant", text: t("gemma.welcome") }]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
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
      } else if (evt.type === "error") {
        setBusy(false);
        setMessages((m) => [...m, { role: "assistant", text: `⚠️ ${evt.message || "Erreur"}` }]);
      } else if (evt.type === "intervention") {
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
        setQaFeedback(null);
        setQaDraft("");
        setQa({
          question: evt.question || "",
          choices: evt.choices ?? null,
          type: evt.question_type || "open",
          mask: evt.mask?.quote ? evt.mask : null,
        });
        // Rappel libre : le passage disparaît de la page le temps de répondre.
        applyMask(evt.mask?.quote ? evt.mask : null);
        setOpen(true);
        // Question automatique : verrouille le scroll sur la page-contexte.
        if (evt.type === "gated_question") setGatedState(true, evt.page);
      } else if (evt.type === "qa_feedback") {
        setBusy(false);
        setQaFeedback({ verdict: evt.verdict || "", feedback: evt.feedback || "", hint: evt.hint || "" });
        // La réponse est donnée : on rend le passage masqué.
        applyMask(null);
        if (Array.isArray(evt.highlights) && evt.highlights.length) {
          onHighlightsRef.current?.(evt.highlights, pageRef.current);
        }
        if (evt.flashcard_created) {
          setMessages((m) => [...m, { role: "system", text: t("gemma.fc_auto_created") }]);
        }
        // Idée principale présente -> déverrouille la lecture.
        if (gatedRef.current && (evt.verdict === "correct" || evt.verdict === "partial")) {
          setGatedState(false);
        }
      }
    };
    // Présence : fenêtre masquée ou application passée au second plan. C'est le
    // seul signal d'absence dont dispose la dérive passive d'attention côté
    // serveur — sans lui, `attention` ne mesurait que la performance aux questions.
    let away = false;
    const reportPresence = () => {
      const hidden = document.hidden || !document.hasFocus();
      if (hidden === away || ws.readyState !== WebSocket.OPEN) return;
      away = hidden;
      ws.send(JSON.stringify({ type: "activity", hidden }));
    };
    document.addEventListener("visibilitychange", reportPresence);
    window.addEventListener("blur", reportPresence);
    window.addEventListener("focus", reportPresence);

    wsRef.current = ws;
    return () => {
      document.removeEventListener("visibilitychange", reportPresence);
      window.removeEventListener("blur", reportPresence);
      window.removeEventListener("focus", reportPresence);
      ws.close();
    };
  }, [docId]);

  useEffect(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "viewport", page: currentPage, session_id: sessionId ?? null }));
  }, [currentPage, sessionId]);

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

  useEffect(() => save(LS_LAYOUT, layout), [layout]);

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
    sendRaw({ type: "ask", question: text, page: pageRef.current, selected_snippets: snippets });
  }

  function action(type: "rephrase" | "recap" | "hook", label: string) {
    if (busy) return;
    setMessages((m) => [...m, { role: "user", text: label }]);
    setBusy(true);
    sendRaw({ type, page: pageRef.current });
  }

  function changeMode(m: (typeof MODES)[number]) {
    setMode(m);
    sendRaw({ type: "mode", mode: m });
  }

  function startQa() {
    if (busy) return;
    setQa(null);
    setQaFeedback(null);
    setBusy(true);
    sendRaw({ type: "start_qa", page: pageRef.current, session_id: sessionId ?? null });
  }

  function submitQa(answer: string) {
    if (busy || !answer.trim() || !qa) return;
    setBusy(true);
    sendRaw({ type: "qa_answer", question: qa.question, answer, page: pageRef.current, session_id: sessionId ?? null });
  }

  async function makeFlashcard(index: number) {
    let front = t("gemma.note_front");
    for (let i = index - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        front = messages[i].text;
        break;
      }
    }
    try {
      // Flashcard intelligente : le LLM réécrit recto/verso en carte autoportante.
      await api.createFlashcardFromExchange(front, messages[index].text, docId, pageRef.current);
      setMessages((m) => [...m, { role: "system", text: t("gemma.fc_created") }]);
    } catch {
      setMessages((m) => [...m, { role: "system", text: t("gemma.fc_failed") }]);
    }
  }

  if (!open) {
    return <GemmaBubble scanning={scanning} onOpen={() => setOpen(true)} title={t("gemma.open")} />;
  }

  return (
    <Rnd
      size={{ width: rect.width, height: rect.height }}
      position={{ x: rect.x, y: rect.y }}
      minWidth={300}
      minHeight={layout === "dockRight" ? 240 : 320}
      bounds="parent"
      disableDragging={layout === "dockRight"}
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
                qu'il change. */}
            <Select value={mode} onValueChange={(v) => changeMode(v as (typeof MODES)[number])}>
              <SelectTrigger
                size="sm"
                aria-label={t("gemma.mode_label")}
                className="h-7 w-auto gap-1 border-border bg-surface text-[11px]"
              >
                <SelectValue />
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
                  className={layout === "dockRight" ? "text-brand" : undefined}
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

        <div ref={bodyRef} style={bodyStyle}>
          {messages.map((m, i) =>
            m.role === "system" ? (
              <div key={i} style={{ alignSelf: "center", fontSize: 11, color: "var(--muted)", fontStyle: "italic" }}>
                {m.text}
              </div>
            ) : (
              <div key={i} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "88%" }}>
                <div
                  style={bubble(m.role)}
                  {...(m.role === "assistant"
                    ? { dangerouslySetInnerHTML: { __html: renderMathToHtml(m.text) } }
                    : { children: m.text })}
                />
                {m.role === "assistant" && i > 0 && (
                  <button
                    onClick={() => makeFlashcard(i)}
                    title={t("gemma.flashcard_hint")}
                    className="mt-1 rounded-[4px] border-none bg-transparent p-0 text-[11px] text-brand
                               underline-offset-2 transition-colors duration-fast ease-brand
                               hover:text-accent-foreground hover:underline
                               focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                  >
                    {t("gemma.flashcard")}
                  </button>
                )}
              </div>
            ),
          )}
          {qa && (
            <QaCard
              qa={qa}
              feedback={qaFeedback}
              draft={qaDraft}
              setDraft={setQaDraft}
              busy={busy}
              locked={gated}
              onSubmit={submitQa}
              onNext={startQa}
              onClose={() => {
                setQa(null);
                setQaFeedback(null);
                applyMask(null);
              }}
            />
          )}
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

        <div style={{ display: "flex", gap: 6, padding: "6px 10px", flexWrap: "wrap", borderTop: "1px solid var(--border)" }}>
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
const contextChipStyle: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, maxWidth: "100%",
  background: "var(--accent-soft)", color: "var(--accent-hover)", border: "1px solid var(--border)",
  borderRadius: 999, padding: "3px 8px", fontSize: 11,
};
const chipClose: React.CSSProperties = {
  border: "none", background: "transparent", color: "var(--accent-hover)", cursor: "pointer", fontSize: 11, padding: 0, lineHeight: 1,
};

// ── Bulle Gemma : sphère 3D à deux yeux mobiles, déplaçable. ────────────────────
// Au repos, les pupilles suivent le curseur. Pendant que Gemma inspecte la page
// (`scanning`), la bulle se tourne vers le PDF et fixe son regard de ce côté.
function GemmaBubble({ scanning, onOpen, title }: { scanning: boolean; onOpen: () => void; title: string }) {
  const SIZE = 64;
  const sphereRef = useRef<HTMLButtonElement>(null);
  const movedRef = useRef(false);
  const [pupil, setPupil] = useState({ x: 0, y: 0 });

  const start: Rect = { ...loadRect(LS_BUBBLE, { x: 0, y: 0, width: SIZE, height: SIZE }) };
  const defaultPos = start.x || start.y
    ? { x: start.x, y: start.y }
    : { x: Math.max(12, window.innerWidth - SIZE - 26), y: Math.max(12, window.innerHeight - SIZE - 26) };

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
      bounds="parent"
      onDragStart={() => { movedRef.current = false; }}
      onDrag={() => { movedRef.current = true; }}
      onDragStop={(_e, d) => save(LS_BUBBLE, { x: d.x, y: d.y, width: SIZE, height: SIZE })}
      style={{ zIndex: 50 }}
    >
      <style>{BUBBLE_KEYFRAMES}</style>
      <div style={{ width: SIZE, height: SIZE, perspective: 320, animation: "gemmaFloat 4.2s ease-in-out infinite" }}>
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
const eyeWhiteStyle: React.CSSProperties = {
  width: 17, height: 17, borderRadius: "50%", background: "#fff",
  display: "grid", placeItems: "center", boxShadow: "inset 0 1px 2px rgba(0,0,0,0.25)",
};
const pupilStyle: React.CSSProperties = {
  width: 7.5, height: 7.5, borderRadius: "50%", background: "#1b1b2b", transition: "transform 0.12s ease-out",
};

function QaCard({
  qa,
  feedback,
  draft,
  setDraft,
  busy,
  locked = false,
  onSubmit,
  onNext,
  onClose,
}: {
  qa: Qa;
  feedback: { verdict: string; feedback: string; hint?: string } | null;
  draft: string;
  setDraft: (v: string) => void;
  busy: boolean;
  locked?: boolean;
  onSubmit: (answer: string) => void;
  onNext: () => void;
  onClose: () => void;
}) {
  const t = useT();
  // Verrouillé + réponse fausse : seule issue = une nouvelle question (pas de sortie).
  const stayLocked = locked && feedback?.verdict === "incorrect";
  return (
    <div
      style={{
        alignSelf: "stretch",
        border: "1px solid var(--accent)",
        borderRadius: "var(--radius-md)",
        background: "var(--surface)",
        padding: 12,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span style={{ fontSize: 11, fontWeight: 700, color: "var(--accent-hover)", letterSpacing: 0.4 }}>{t("flash.q")}</span>
        <QuestionTypeBadge type={qa.type} />
      </div>
      <QuestionStem question={qa.question} type={qa.type} masked={Boolean(qa.mask)} />

      {!feedback && (
        <AnswerInput
          // Une nouvelle question doit repartir d'un widget vierge (étapes
          // remélangées, ordre remis à zéro) : la question sert de clé.
          key={qa.question}
          type={qa.type}
          choices={qa.choices}
          seed={qa.question}
          draft={draft}
          setDraft={setDraft}
          busy={busy}
          onSubmit={onSubmit}
        />
      )}

      {feedback && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <VerdictBadge verdict={feedback.verdict} />
          <div style={{ fontSize: 13, color: "var(--text-soft)" }}>{feedback.feedback}</div>
          {feedback.hint && feedback.verdict === "incorrect" && (
            <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Lightbulb className="mt-px size-3.5 shrink-0 text-warning" aria-hidden />
              {feedback.hint}
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onNext} disabled={busy} style={{ ...chip, borderColor: "var(--accent)", color: "var(--accent-hover)" }}>
              {stayLocked ? t("gemma.retry_question") : t("gemma.new_question")}
            </button>
            {!stayLocked && (
              <button onClick={onClose} style={chip}>
                {t("gemma.finish")}
              </button>
            )}
          </div>
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
