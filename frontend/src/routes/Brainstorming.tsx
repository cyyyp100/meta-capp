import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { ChatPanel } from "../features/brainstorming/ChatPanel";
import { DiscussionList } from "../features/brainstorming/DiscussionList";
import { useT } from "../i18n";

const QK = ["brainstorming", "discussions"];

export function Brainstorming() {
  const t = useT();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  const { data: discussions } = useQuery({ queryKey: QK, queryFn: api.brainstormDiscussions });

  // Sélectionne la 1re discussion par défaut quand la liste arrive.
  useEffect(() => {
    if (selectedId === null && discussions && discussions.length > 0) {
      setSelectedId(discussions[0].id);
    }
  }, [discussions, selectedId]);

  async function createDiscussion() {
    if (creating) return;
    setCreating(true);
    try {
      const created = await api.createDiscussion();
      await qc.invalidateQueries({ queryKey: QK });
      setSelectedId(created.id);
    } finally {
      setCreating(false);
    }
  }

  async function deleteDiscussion(id: number) {
    await api.deleteDiscussion(id);
    if (selectedId === id) setSelectedId(null);
    qc.invalidateQueries({ queryKey: QK });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "var(--space-lg)", gap: "var(--space-md)" }}>
      <header>
        <h1 style={{ margin: 0, fontSize: 22 }}>💭 {t("brainstorm.title")}</h1>
        <p style={{ margin: "4px 0 0", color: "var(--muted)", fontSize: 13 }}>{t("brainstorm.subtitle")}</p>
      </header>

      <div style={{ display: "flex", gap: "var(--space-lg)", flex: 1, minHeight: 0 }}>
        <aside style={{ width: 260, display: "flex", flexDirection: "column", gap: 10, minHeight: 0 }}>
          <button onClick={createDiscussion} disabled={creating} style={newBtn}>
            {creating ? t("common.loading") : t("brainstorm.new")}
          </button>
          <DiscussionList
            discussions={discussions ?? []}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onDelete={deleteDiscussion}
          />
        </aside>

        <main style={{ flex: 1, minWidth: 0 }}>
          {selectedId !== null ? (
            <ChatPanel
              key={selectedId}
              discussionId={selectedId}
              onActivity={() => qc.invalidateQueries({ queryKey: QK })}
            />
          ) : (
            <div style={placeholder}>{t("brainstorm.pick")}</div>
          )}
        </main>
      </div>
    </div>
  );
}

const newBtn: React.CSSProperties = {
  border: "1px solid var(--accent)",
  background: "var(--accent-soft)",
  color: "var(--accent-hover)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 12px",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: 13,
};

const placeholder: React.CSSProperties = {
  height: "100%",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: "var(--muted)",
  fontSize: 14,
  border: "1px dashed var(--border)",
  borderRadius: "var(--radius-md)",
};
