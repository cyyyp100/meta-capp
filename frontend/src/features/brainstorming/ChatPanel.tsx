import { useEffect, useRef, useState } from "react";

import type { BrainstormSource } from "../../api/client";
import { api } from "../../api/client";
import { wsTokenSuffix } from "../../api/security";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
import { renderMathToHtml } from "../reader/renderMath";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: BrainstormSource[];
}

const SOURCE_ICON: Record<BrainstormSource["source_type"], string> = {
  highlight: "🖍",
  qa: "💬",
  flashcard: "🗂",
  document: "📄",
};

export function ChatPanel({ discussionId, onActivity }: { discussionId: number; onActivity?: () => void }) {
  const t = useT();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [scanning, setScanning] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  // Historique persistant : recharge les messages à l'ouverture d'une discussion.
  useEffect(() => {
    let alive = true;
    setMessages([]);
    setBusy(false);
    setScanning(false);
    api
      .discussionMessages(discussionId)
      .then((d) => {
        if (alive) setMessages(d.messages.map((m) => ({ role: m.role, content: m.content, sources: m.sources })));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [discussionId]);

  // Canal temps réel dédié à la discussion courante.
  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/brainstorming/${discussionId}/stream${wsTokenSuffix()}`);
    ws.onmessage = (e) => {
      const evt = JSON.parse(e.data);
      if (evt.type === "scanning") {
        setScanning(Boolean(evt.active));
      } else if (evt.type === "answer") {
        setBusy(false);
        setScanning(false);
        setMessages((m) => [...m, { role: "assistant", content: evt.answer || "", sources: evt.sources || [] }]);
        onActivity?.();
      } else if (evt.type === "error") {
        setBusy(false);
        setScanning(false);
        setMessages((m) => [...m, { role: "assistant", content: `⚠️ ${evt.message || ""}` }]);
      }
    };
    wsRef.current = ws;
    return () => ws.close();
  }, [discussionId]);

  // Auto-scroll vers le dernier message.
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy, scanning]);

  function ask() {
    const text = draft.trim();
    if (!text || busy) return;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setMessages((m) => [...m, { role: "assistant", content: `⚠️ ${t("brainstorm.unavailable")}` }]);
      return;
    }
    setMessages((m) => [...m, { role: "user", content: text }]);
    setDraft("");
    setBusy(true);
    ws.send(JSON.stringify({ type: "ask", question: text }));
  }

  return (
    <div style={panel}>
      <div ref={bodyRef} style={body}>
        {messages.length === 0 && !busy && <div style={welcome}>{t("brainstorm.welcome")}</div>}
        {messages.map((m, i) => (
          <div key={i} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "82%" }}>
            <div
              style={bubble(m.role)}
              {...(m.role === "assistant"
                ? { dangerouslySetInnerHTML: { __html: renderMathToHtml(m.content) } }
                : { children: m.content })}
            />
            {m.sources && m.sources.length > 0 && <Sources sources={m.sources} label={t("brainstorm.sources")} />}
          </div>
        ))}
        {scanning && <div style={hint}>🔎 {t("brainstorm.searching")}</div>}
        {busy && !scanning && <div style={hint}>{t("brainstorm.thinking")}</div>}
      </div>
      <div style={inputBar}>
        <AutoGrowTextarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onSubmit={ask}
          placeholder={t("brainstorm.placeholder")}
          style={input}
        />
        <button onClick={ask} disabled={busy} style={{ ...sendBtn, background: busy ? "var(--muted-light)" : "var(--accent)" }}>
          ↵
        </button>
      </div>
    </div>
  );
}

function Sources({ sources, label }: { sources: BrainstormSource[]; label: string }) {
  return (
    <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5, color: "var(--muted)" }}>📎 {label}</div>
      {sources.map((s, i) => (
        <div key={i} style={sourceItem}>
          <span>{SOURCE_ICON[s.source_type] || "•"}</span>
          <span>
            {s.doc_title && (
              <strong style={{ color: "var(--text-soft)" }}>
                {s.doc_title}
                {s.page ? `, p.${s.page}` : ""} —{" "}
              </strong>
            )}
            <span style={{ color: "var(--muted)" }}>{s.snippet}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

const panel: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "100%",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface)",
  overflow: "hidden",
};

const body: React.CSSProperties = {
  flex: 1,
  overflow: "auto",
  padding: "var(--space-lg)",
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

const welcome: React.CSSProperties = {
  margin: "auto",
  maxWidth: 460,
  textAlign: "center",
  color: "var(--muted)",
  fontSize: 14,
  lineHeight: 1.5,
};

const hint: React.CSSProperties = { alignSelf: "flex-start", fontSize: 12, color: "var(--muted)", fontStyle: "italic" };

const sourceItem: React.CSSProperties = { display: "flex", gap: 6, fontSize: 12, lineHeight: 1.4 };

const inputBar: React.CSSProperties = { display: "flex", alignItems: "flex-end", gap: 8, padding: 10, borderTop: "1px solid var(--border)" };

const input: React.CSSProperties = {
  flex: 1,
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 12px",
  background: "var(--bg)",
  color: "var(--text)",
  fontSize: 14,
};

const sendBtn: React.CSSProperties = {
  border: "none",
  color: "var(--on-accent)",
  borderRadius: "var(--radius-sm)",
  padding: "0 16px",
  height: 40,
  cursor: "pointer",
  fontWeight: 600,
  fontSize: 16,
};

function bubble(role: "user" | "assistant"): React.CSSProperties {
  return {
    padding: "9px 13px",
    borderRadius: 14,
    fontSize: 14,
    lineHeight: 1.5,
    whiteSpace: "pre-wrap",
    background: role === "user" ? "var(--accent-soft)" : "var(--surface-soft)",
    color: role === "user" ? "var(--accent-hover)" : "var(--text)",
    border: "1px solid var(--border)",
  };
}
