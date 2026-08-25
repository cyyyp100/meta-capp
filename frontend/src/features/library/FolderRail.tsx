// features/library/FolderRail.tsx — La colonne de gauche de la bibliothèque.
//
// Trois entrées pseudo en tête (Tous / Récents / Non classés) puis l'arbre.
// « Tous » et « Non classés » sont aussi des cibles de dépôt : c'est par elles
// qu'on sort un document d'un dossier à la souris.
import { Clock, File, Files, FolderPlus, type LucideIcon } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

import type { FolderNode } from "../../api/types";
import { useT } from "../../i18n";
import { DOC_MIME, FOLDER_MIME, hasType, readId } from "./dnd";
import { FolderRow, type FolderRowHandlers } from "./FolderRow";
import { useLibraryUi } from "./useLibraryUi";

export function FolderRail({
  tree,
  counts,
  handlers,
  onCreateRoot,
}: {
  tree: FolderNode[];
  counts: { all: number; recent: number; unfiled: number };
  handlers: FolderRowHandlers;
  onCreateRoot: (name: string) => void;
}) {
  const t = useT();
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState("");
  const selection = useLibraryUi((s) => s.selection);
  const select = useLibraryUi((s) => s.select);

  function commitCreate() {
    setCreating(false);
    const name = draft.trim();
    setDraft("");
    if (name) onCreateRoot(name);
  }

  return (
    <aside style={rail}>
      <PseudoRow
        label={t("library.all")}
        Icon={Files}
        count={counts.all}
        active={selection.kind === "all"}
        onSelect={() => select({ kind: "all" })}
        // Déposer sur « Tous » = sortir le document de son dossier.
        onDropDocument={(docId) => handlers.onDropDocument(docId, null)}
        onDropFolder={(folderId) => handlers.onDropFolder(folderId, null)}
      />
      <PseudoRow
        label={t("library.recent")}
        Icon={Clock}
        count={counts.recent}
        active={selection.kind === "recent"}
        onSelect={() => select({ kind: "recent" })}
      />
      <PseudoRow
        label={t("library.unfiled")}
        Icon={File}
        count={counts.unfiled}
        active={selection.kind === "unfiled"}
        onSelect={() => select({ kind: "unfiled" })}
        onDropDocument={(docId) => handlers.onDropDocument(docId, null)}
        onDropFolder={(folderId) => handlers.onDropFolder(folderId, null)}
      />

      <div style={separator} />
      <div style={sectionTitle}>{t("library.folders")}</div>

      <div role="tree" aria-label={t("library.folders")} style={{ display: "flex", flexDirection: "column", gap: 1 }}>
        {tree.map((folder) => (
          <FolderRow
            key={folder.id}
            folder={folder}
            depth={0}
            tree={tree}
            selection={selection}
            handlers={handlers}
          />
        ))}
      </div>

      {tree.length === 0 && !creating && <p style={emptyHint}>{t("library.folders_empty")}</p>}

      {creating ? (
        <input
          autoFocus
          value={draft}
          placeholder={t("library.folder_name_placeholder")}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitCreate}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitCreate();
            if (e.key === "Escape") {
              setDraft("");
              setCreating(false);
            }
          }}
          style={createInput}
        />
      ) : (
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="mt-2 flex items-center gap-2 rounded-sm border border-dashed border-border-strong
                     bg-transparent px-2.5 py-1.5 text-left text-xs font-semibold text-muted-foreground
                     transition-colors duration-fast ease-brand
                     hover:border-brand hover:bg-brand-soft hover:text-accent-foreground
                     focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <FolderPlus className="size-3.5 shrink-0" aria-hidden />
          {t("library.new_folder")}
        </button>
      )}
    </aside>
  );
}

/** Une entrée non-dossier du rail, éventuellement cible de dépôt. */
function PseudoRow({
  label,
  Icon,
  count,
  active,
  onSelect,
  onDropDocument,
  onDropFolder,
}: {
  label: string;
  Icon: LucideIcon;
  count: number;
  active: boolean;
  onSelect: () => void;
  onDropDocument?: (docId: number) => void;
  onDropFolder?: (folderId: number) => void;
}) {
  const [over, setOver] = useState(false);
  const droppable = Boolean(onDropDocument || onDropFolder);

  function accepts(dt: DataTransfer): boolean {
    if (!droppable) return false;
    if (hasType(dt, DOC_MIME)) return Boolean(onDropDocument);
    if (hasType(dt, FOLDER_MIME)) return Boolean(onDropFolder);
    return false;
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      onDragEnter={(e) => {
        if (!accepts(e.dataTransfer)) return;
        e.preventDefault();
        setOver(true);
      }}
      onDragOver={(e) => {
        if (!accepts(e.dataTransfer)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
      }}
      onDragLeave={(e) => {
        if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
        setOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const docId = readId(e.dataTransfer, DOC_MIME);
        if (docId !== null) {
          onDropDocument?.(docId);
          return;
        }
        const folderId = readId(e.dataTransfer, FOLDER_MIME);
        if (folderId !== null) onDropFolder?.(folderId);
      }}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] select-none",
        "outline-2 -outline-offset-2 outline-transparent",
        "transition-[background-color,color,outline-color] duration-fast ease-brand",
        "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
        over || active
          ? "bg-accent text-accent-foreground"
          : "text-text-soft hover:bg-accent/60 hover:text-accent-foreground",
        // Cible de dépôt survolée : le liseré dit « on lâche ici ».
        over && "outline-brand",
      )}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <span className="text-[11px] text-muted-foreground tabular-nums">
        {count > 0 ? count : ""}
      </span>
    </div>
  );
}

const rail: React.CSSProperties = {
  width: 240,
  flexShrink: 0,
  display: "flex",
  flexDirection: "column",
  gap: 1,
  overflowY: "auto",
  paddingRight: "var(--space-xs)",
};


const separator: React.CSSProperties = {
  height: 1,
  background: "var(--border)",
  margin: "var(--space-sm) 4px",
};

const sectionTitle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--muted)",
  padding: "0 8px 6px",
};

const emptyHint: React.CSSProperties = {
  fontSize: 12,
  color: "var(--muted)",
  padding: "4px 8px",
  lineHeight: 1.4,
  margin: 0,
};


const createInput: React.CSSProperties = {
  marginTop: "var(--space-sm)",
  font: "inherit",
  fontSize: 13,
  padding: "6px 9px",
  border: "1px solid var(--accent)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface)",
  color: "var(--text)",
};
