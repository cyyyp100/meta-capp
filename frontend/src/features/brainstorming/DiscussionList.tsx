import type { BrainstormDiscussion } from "../../api/client";
import { useT } from "../../i18n";

export function DiscussionList({
  discussions,
  selectedId,
  onSelect,
  onDelete,
}: {
  discussions: BrainstormDiscussion[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  const t = useT();
  if (discussions.length === 0) {
    return <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 4px", lineHeight: 1.5 }}>{t("brainstorm.empty")}</div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, overflow: "auto" }}>
      {discussions.map((d) => {
        const active = d.id === selectedId;
        return (
          <div
            key={d.id}
            onClick={() => onSelect(d.id)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "9px 11px",
              borderRadius: "var(--radius-sm)",
              cursor: "pointer",
              border: "1px solid",
              borderColor: active ? "var(--accent)" : "transparent",
              background: active ? "var(--accent-soft)" : "transparent",
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: active ? "var(--accent-hover)" : "var(--text)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {d.title}
              </div>
              {d.summary && (
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--muted)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {d.summary}
                </div>
              )}
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (window.confirm(t("brainstorm.delete_confirm"))) onDelete(d.id);
              }}
              title="🗑"
              style={{
                border: "none",
                background: "transparent",
                color: "var(--muted)",
                cursor: "pointer",
                fontSize: 13,
                padding: 2,
              }}
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
