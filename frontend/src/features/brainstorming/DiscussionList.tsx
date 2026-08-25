import { Trash2 } from "lucide-react";

import { useConfirm } from "@/components/ui/confirm";

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
  const confirm = useConfirm();
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
                void (async () => {
                  const ok = await confirm({
                    title: t("brainstorm.delete_confirm"),
                    confirmLabel: t("common.delete"),
                    destructive: true,
                  });
                  if (ok) onDelete(d.id);
                })();
              }}
              title={t("common.delete")}
              aria-label={t("common.delete")}
              className="flex rounded-[4px] border-none bg-transparent p-0.5 text-muted-foreground
                         transition-colors duration-fast ease-brand
                         hover:bg-danger-soft hover:text-danger
                         focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              <Trash2 className="size-3.5" aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}
