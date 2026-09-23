import { useEffect, useRef, useState } from "react";

import type { BrainstormDiscussion, BrainstormMessage, BrainstormSource } from "../../api/client";
import { api } from "../../api/client";
import { wsTokenSuffix } from "../../api/security";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
import { renderMathToHtml } from "../reader/renderMath";
import { FolderScopePicker } from "./FolderScopePicker";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: BrainstormSource[];
}

// Réponse partie d'un autre canal (discussion quittée puis rouverte) : on relit
// la discussion à ce rythme jusqu'à ce que le serveur l'ait livrée.
const PENDING_POLL_MS = 2000;

function toChat(messages: BrainstormMessage[]): ChatMessage[] {
  return messages.map((m) => ({ role: m.role, content: m.content, sources: m.sources }));
}

const SOURCE_ICON: Record<BrainstormSource["source_type"], string> = {
  highlight: "🖍",
  qa: "💬",
  flashcard: "🗂",
  document: "📄",
  mistake: "❌",
};

export function ChatPanel({
  discussionId,
  discussion,
  focusNonce,
  onFolderChange,
  onActivity,
}: {
  discussionId: number;
  /** Ligne de la liste (titre, dossier lié) — absente le temps qu'elle arrive. */
  discussion?: BrainstormDiscussion;
  /** Change à chaque « Nouvelle discussion » : redonne le focus au champ de saisie. */
  focusNonce?: number;
  onFolderChange: (folderId: number | null) => void;
  onActivity?: () => void;
}) {
  const t = useT();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  // Le serveur répond déjà à une question posée depuis un canal précédent.
  const [pending, setPending] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [disconnected, setDisconnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const waiting = busy || pending;

  // Historique persistant : recharge les messages à l'ouverture d'une discussion.
  useEffect(() => {
    let alive = true;
    setMessages([]);
    setBusy(false);
    setPending(false);
    setScanning(false);
    api
      .discussionMessages(discussionId)
      .then((d) => {
        if (!alive) return;
        setMessages(toChat(d.messages));
        setPending(d.answering);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [discussionId]);

  // Une réponse est due mais ce canal ne la recevra pas : on relit la discussion
  // jusqu'à ce qu'elle y soit, au lieu de laisser poser une seconde question.
  useEffect(() => {
    if (!pending) return;
    let alive = true;
    const timer = window.setInterval(() => {
      api
        .discussionMessages(discussionId)
        .then((d) => {
          if (!alive || d.answering) return;
          setMessages(toChat(d.messages));
          setPending(false);
        })
        .catch(() => {});
    }, PENDING_POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [pending, discussionId]);

  useEffect(() => {
    composerRef.current?.focus();
  }, [focusNonce]);

  // Canal temps réel dédié à la discussion courante.
  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/brainstorming/${discussionId}/stream${wsTokenSuffix()}`);
    ws.onmessage = (e) => {
      let evt;
      try {
        evt = JSON.parse(e.data);
      } catch {
        return; // trame illisible : ignorée
      }
      if (evt.type === "scanning") {
        setScanning(Boolean(evt.active));
      } else if (evt.type === "title") {
        // 1er message : le serveur vient de nommer la discussion, la liste le
        // montre tout de suite au lieu d'attendre la réponse de Gemma.
        onActivity?.();
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
    // Coupure inattendue : la réponse attendue n'arrivera plus par ce canal. On
    // débloque la saisie et on le dit, au lieu d'afficher « réfléchit » à vie.
    ws.onclose = () => {
      setBusy(false);
      setScanning(false);
      setDisconnected(true);
    };
    wsRef.current = ws;
    return () => {
      ws.onclose = null; // fermeture voulue (changement de discussion) : pas d'alerte
      ws.close();
    };
  }, [discussionId]);

  // Auto-scroll vers le dernier message.
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, waiting, scanning, disconnected]);

  function ask() {
    const text = draft.trim();
    if (!text || waiting) return;
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

  const folderId = discussion?.folder_id ?? null;
  const folderName = discussion?.folder_name ?? null;

  return (
    <div style={panel}>
      <div style={header}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={headerTitle}>{discussion?.title ?? ""}</div>
          <div style={{ fontSize: 11, color: "var(--muted)", ...ellipsis }}>
            {folderId !== null
              ? t("brainstorm.scope_hint", { name: folderName ?? "" })
              : t("brainstorm.scope_all_hint")}
          </div>
        </div>
        <FolderScopePicker folderId={folderId} folderName={folderName} onChange={onFolderChange} />
      </div>
      <div ref={bodyRef} style={body}>
        {messages.length === 0 && !waiting && (
          <div style={welcome}>
            {t("brainstorm.welcome")}
            {folderId === null && <div style={{ marginTop: 10, fontSize: 13 }}>{t("brainstorm.welcome_folder")}</div>}
          </div>
        )}
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
        {waiting && !scanning && <div style={hint}>{t("brainstorm.thinking")}</div>}
        {disconnected && <div style={hint}>⚠️ {t("brainstorm.disconnected")}</div>}
      </div>
      <div style={inputBar}>
        <AutoGrowTextarea
          ref={composerRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onSubmit={ask}
          placeholder={t("brainstorm.placeholder")}
          style={input}
        />
        <button onClick={ask} disabled={waiting} style={{ ...sendBtn, background: waiting ? "var(--muted-light)" : "var(--accent)" }}>
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

const ellipsis: React.CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };

const header: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "10px 14px",
  borderBottom: "1px solid var(--border)",
};

const headerTitle: React.CSSProperties = { fontSize: 14, fontWeight: 600, color: "var(--text)", ...ellipsis };

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
