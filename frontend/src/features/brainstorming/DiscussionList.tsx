import { Folder, Pin, PinOff, Trash2 } from "lucide-react";

import { useConfirm } from "@/components/ui/confirm";
import { cn } from "@/lib/utils";

import type { BrainstormDiscussion } from "../../api/client";
import { useT } from "../../i18n";

const iconBtn =
  "flex rounded-[4px] border-none bg-transparent p-0.5 text-muted-foreground " +
  "transition-[color,background-color,opacity] duration-fast ease-brand " +
  "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none";

export function DiscussionList({
  discussions,
  selectedId,
  onSelect,
  onDelete,
  onTogglePin,
}: {
  discussions: BrainstormDiscussion[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
  onTogglePin: (id: number, pinned: boolean) => void;
}) {
  const t = useT();
  if (discussions.length === 0) {
    return <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 4px", lineHeight: 1.5 }}>{t("brainstorm.empty")}</div>;
  }
  // Le serveur trie déjà (épinglées d'abord) : on ne fait que couper la liste.
  const pinned = discussions.filter((d) => d.pinned_at);
  const others = discussions.filter((d) => !d.pinned_at);
  const row = (d: BrainstormDiscussion) => (
    <DiscussionRow
      key={d.id}
      discussion={d}
      active={d.id === selectedId}
      onSelect={onSelect}
      onDelete={onDelete}
      onTogglePin={onTogglePin}
    />
  );
  // `flex: 1` + `minHeight: 0` : la liste prend la hauteur restante du rail et
  // défile d'elle-même, au lieu de pousser toute la page.
  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
      {pinned.length > 0 && (
        <>
          <div style={sectionLabel}>{t("brainstorm.pinned")}</div>
          {pinned.map(row)}
          <div style={{ ...sectionLabel, marginTop: 6 }}>{t("brainstorm.recent")}</div>
        </>
      )}
      {others.map(row)}
    </div>
  );
}

function DiscussionRow({
  discussion: d,
  active,
  onSelect,
  onDelete,
  onTogglePin,
}: {
  discussion: BrainstormDiscussion;
  active: boolean;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
  onTogglePin: (id: number, pinned: boolean) => void;
}) {
  const t = useT();
  const confirm = useConfirm();
  const isPinned = Boolean(d.pinned_at);
  return (
    <div
      onClick={() => onSelect(d.id)}
      className="group"
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
        flexShrink: 0,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: active ? "var(--accent-hover)" : "var(--text)",
            ...ellipsis,
          }}
        >
          {d.title}
        </div>
        {d.folder_name ? (
          <div style={{ fontSize: 11, color: "var(--muted)", display: "flex", alignItems: "center", gap: 4, minWidth: 0 }}>
            <Folder className="size-3 shrink-0" aria-hidden />
            <span style={ellipsis}>{d.folder_name}</span>
          </div>
        ) : (
          d.summary && <div style={{ fontSize: 11, color: "var(--muted)", ...ellipsis }}>{d.summary}</div>
        )}
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onTogglePin(d.id, !isPinned);
        }}
        title={isPinned ? t("brainstorm.unpin") : t("brainstorm.pin")}
        aria-label={isPinned ? t("brainstorm.unpin") : t("brainstorm.pin")}
        aria-pressed={isPinned}
        // Épinglée : l'icône reste visible (c'est l'état de la ligne). Sinon elle
        // n'apparaît qu'au survol ou au focus clavier, pour ne pas charger la liste.
        className={cn(
          iconBtn,
          "group/pin hover:bg-accent hover:text-accent-foreground",
          isPinned ? "text-brand-ink" : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
        )}
      >
        {/* Épingle pleine = épinglée ; survoler le bouton montre l'action inverse. */}
        {isPinned ? (
          <>
            <Pin className="size-3.5 fill-current group-hover/pin:hidden" aria-hidden />
            <PinOff className="hidden size-3.5 group-hover/pin:block" aria-hidden />
          </>
        ) : (
          <Pin className="size-3.5" aria-hidden />
        )}
      </button>
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
        className={cn(iconBtn, "hover:bg-danger-soft hover:text-danger")}
      >
        <Trash2 className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}

const ellipsis: React.CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };

const sectionLabel: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: 0.5,
  color: "var(--muted)",
  padding: "0 4px",
  flexShrink: 0,
};
