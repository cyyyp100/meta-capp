import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Rnd } from "react-rnd";

import { api } from "../../api/client";
import { wsTokenSuffix } from "../../api/security";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
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
}: {
  docId: number;
  currentPage: number;
  sessionId?: number | null;
  onHighlights?: (items: Highlight[], page: number) => void;
  contextChips?: { id: number; page: number; text: string }[];
  onRemoveContextChip?: (id: number) => void;
  onGatedChange?: (active: boolean, page?: number) => void;
}) {
  const t = useT();
  // Gemma démarre fermé : l'utilisateur (ou une intervention) l'ouvre au besoin.
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [mode, setMode] = useState<(typeof MODES)[number]>("normal");
  const [qa, setQa] = useState<{ question: string; choices: string[] | null; type: string } | null>(null);
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
  const contextChipsRef = useRef(contextChips);
  contextChipsRef.current = contextChips;
  const gatedRef = useRef(false);
  gatedRef.current = gated;
  const bodyRef = useRef<HTMLDivElement>(null);

  function setGatedState(active: boolean, page?: number) {
    setGated(active);
    onGatedChangeRef.current?.(active, page);
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
      } else if (evt.type === "qa_question") {
        setBusy(false);
        setQaFeedback(null);
        setQaDraft("");
        setQa({ question: evt.question || "", choices: evt.choices ?? null, type: evt.question_type || "open" });
        setOpen(true);
      } else if (evt.type === "gated_question") {
        // Question automatique : verrouille le scroll sur la page-contexte.
        setBusy(false);
        setQaFeedback(null);
        setQaDraft("");
        setQa({ question: evt.question || "", choices: evt.choices ?? null, type: evt.question_type || "open" });
        setOpen(true);
        setGatedState(true, evt.page);
      } else if (evt.type === "qa_feedback") {
        setBusy(false);
        setQaFeedback({ verdict: evt.verdict || "", feedback: evt.feedback || "", hint: evt.hint || "" });
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
    wsRef.current = ws;
    return () => ws.close();
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
    let front = "Note de lecture";
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
          <strong style={{ color: "var(--accent-hover)", fontSize: 14 }}>
            ✦ Gemma <span style={{ fontSize: 10 }}>{connected ? "🟢" : "⚪️"}</span>
          </strong>
          <div className="gemma-nodrag" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <select
              value={mode}
              onChange={(e) => changeMode(e.target.value as (typeof MODES)[number])}
              title="Mode d'accompagnement"
              style={{ fontSize: 11, border: "1px solid var(--border)", borderRadius: 6, background: "var(--surface)", color: "var(--text)", padding: "2px 4px" }}
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <button onClick={() => sendRaw({ type: "focus" })} title="Mode focus (pause des interruptions)" style={iconBtn}>
              🎯
            </button>
            <button
              onClick={() => setLayout(layout === "dockRight" ? "float" : "dockRight")}
              title={layout === "dockRight" ? t("gemma.float") : t("gemma.dock_right")}
              style={{ ...iconBtn, color: layout === "dockRight" ? "var(--accent)" : "var(--muted)" }}
            >
              {layout === "dockRight" ? "⤢" : "▭"}
            </button>
            {!gated && (
              <button onClick={() => setOpen(false)} style={iconBtn}>
                ✕
              </button>
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
                  <button onClick={() => makeFlashcard(i)} style={miniBtn} title="Flashcard">
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
              }}
            />
          )}
          {busy && <div style={{ alignSelf: "flex-start", fontSize: 12, color: "var(--muted)", fontStyle: "italic" }}>{t("gemma.thinking")}</div>}
        </div>

        <div style={{ display: "flex", gap: 6, padding: "6px 10px", flexWrap: "wrap", borderTop: "1px solid var(--border)" }}>
          <button disabled={busy} onClick={() => action("rephrase", t("gemma.rephrase_cmd"))} style={chip}>
            {t("gemma.rephrase")}
          </button>
          <button disabled={busy} onClick={() => action("recap", t("gemma.recap_cmd"))} style={chip}>
            {t("gemma.recap")}
          </button>
          <button disabled={busy} onClick={() => action("hook", t("gemma.curiosity_cmd"))} style={chip}>
            {t("gemma.curiosity")}
          </button>
          <button disabled={busy} onClick={startQa} style={{ ...chip, borderColor: "var(--accent)", color: "var(--accent-hover)" }}>
            {t("gemma.quizme")}
          </button>
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
          <button onClick={ask} disabled={busy} style={{ ...sendBtn, background: busy ? "var(--muted-light)" : "var(--accent)" }}>
            ↵
          </button>
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
const iconBtn: React.CSSProperties = { border: "none", background: "transparent", cursor: "pointer", color: "var(--muted)", fontSize: 15 };
const inputStyle: React.CSSProperties = {
  flex: 1, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "8px 10px",
  background: "var(--bg)", color: "var(--text)", fontSize: 13,
};
const sendBtn: React.CSSProperties = { border: "none", color: "#fff", borderRadius: "var(--radius-sm)", padding: "0 14px", height: 36, cursor: "pointer", fontWeight: 600 };
const chip: React.CSSProperties = {
  border: "1px solid var(--border)", background: "var(--surface-soft)", color: "var(--text-soft)",
  borderRadius: 999, padding: "4px 10px", fontSize: 12, cursor: "pointer",
};
const miniBtn: React.CSSProperties = {
  marginTop: 4, border: "none", background: "transparent", color: "var(--accent)", cursor: "pointer", fontSize: 11, padding: 0,
};
const contextChipStyle: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, maxWidth: "100%",
  background: "var(--accent-soft)", color: "var(--accent-hover)", border: "1px solid var(--border)",
  borderRadius: 999, padding: "3px 8px", fontSize: 11,
};
const chipClose: React.CSSProperties = {
  border: "none", background: "transparent", color: "var(--accent-hover)", cursor: "pointer", fontSize: 11, padding: 0, lineHeight: 1,
};

const VERDICT_COLOR: Record<string, string> = {
  correct: "var(--success)",
  partial: "var(--warning)",
  incorrect: "var(--danger)",
};

// ── Bulle Gemma : sphère 3D à deux yeux mobiles, déplaçable. ────────────────────
// Au repos, les pupilles suivent le curseur. Pendant que Gemma inspecte la page
// (`scanning`), la bulle se tourne vers le PDF et fixe son regard de ce côté.
function GemmaBubble({ scanning, onOpen, title }: { scanning: boolean; onOpen: () => void; title: string }) {
  const SIZE = 64;
  const sphereRef = useRef<HTMLDivElement>(null);
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
        <div
          ref={sphereRef}
          title={title}
          onClick={() => { if (!movedRef.current) onOpen(); }}
          style={{ ...sphereStyle, transform: scanning ? "rotateY(-32deg) scale(1.04)" : "rotateY(0deg) scale(1)" }}
        >
          <div style={{ display: "flex", gap: 9, transform: "translateZ(10px)" }}>
            <Eye look={look} />
            <Eye look={look} />
          </div>
        </div>
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
  qa: { question: string; choices: string[] | null; type: string };
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
  const hasChoices = Array.isArray(qa.choices) && qa.choices.length > 0;
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
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--accent-hover)", letterSpacing: 0.4 }}>{t("flash.q")}</div>
      <div style={{ fontSize: 13, fontWeight: 600 }}>{qa.question || "…"}</div>

      {!feedback &&
        (hasChoices ? (
          <div style={{ display: "grid", gap: 6 }}>
            {qa.choices!.map((c) => (
              <button key={c} disabled={busy} onClick={() => onSubmit(c)} style={{ ...chip, textAlign: "left", borderRadius: "var(--radius-sm)" }}>
                {c}
              </button>
            ))}
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "flex-end", gap: 6 }}>
            <AutoGrowTextarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onSubmit={() => onSubmit(draft)}
              placeholder={t("gemma.your_answer")}
              style={inputStyle}
            />
            <button onClick={() => onSubmit(draft)} disabled={busy} style={{ ...sendBtn, background: busy ? "var(--muted-light)" : "var(--accent)" }}>
              OK
            </button>
          </div>
        ))}

      {feedback && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span
            style={{
              alignSelf: "flex-start",
              fontSize: 11,
              fontWeight: 700,
              padding: "3px 10px",
              borderRadius: 999,
              color: "#fff",
              background: VERDICT_COLOR[feedback.verdict] ?? "var(--muted)",
            }}
          >
            {t(`verdict.${feedback.verdict}`)}
          </span>
          <div style={{ fontSize: 13, color: "var(--text-soft)" }}>{feedback.feedback}</div>
          {feedback.hint && feedback.verdict === "incorrect" && (
            <div style={{ fontSize: 12, color: "var(--muted)", fontStyle: "italic" }}>💡 {feedback.hint}</div>
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
