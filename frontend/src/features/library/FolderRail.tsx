// features/library/FolderRail.tsx — La colonne de gauche de la bibliothèque.
//
// Trois entrées pseudo en tête (Tous / Récents / Non classés) puis l'arbre.
// « Tous » et « Non classés » sont aussi des cibles de dépôt : c'est par elles
// qu'on sort un document d'un dossier à la souris.
import { useState } from "react";

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
        icon="📚"
        count={counts.all}
        active={selection.kind === "all"}
        onSelect={() => select({ kind: "all" })}
        // Déposer sur « Tous » = sortir le document de son dossier.
        onDropDocument={(docId) => handlers.onDropDocument(docId, null)}
        onDropFolder={(folderId) => handlers.onDropFolder(folderId, null)}
      />
      <PseudoRow
        label={t("library.recent")}
        icon="🕒"
        count={counts.recent}
        active={selection.kind === "recent"}
        onSelect={() => select({ kind: "recent" })}
      />
      <PseudoRow
        label={t("library.unfiled")}
        icon="📄"
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
        <button type="button" onClick={() => setCreating(true)} style={newFolderButton}>
          {t("library.new_folder")}
        </button>
      )}
    </aside>
  );
}

/** Une entrée non-dossier du rail, éventuellement cible de dépôt. */
function PseudoRow({
  label,
  icon,
  count,
  active,
  onSelect,
  onDropDocument,
  onDropFolder,
}: {
  label: string;
  icon: string;
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
      style={{
        ...pseudoRow,
        background: over || active ? "var(--accent-soft)" : "transparent",
        color: over || active ? "var(--accent-hover)" : "var(--text-soft)",
        outline: over ? "2px solid var(--accent)" : "2px solid transparent",
        outlineOffset: -2,
      }}
    >
      <span aria-hidden="true" style={{ fontSize: 13 }}>
        {icon}
      </span>
      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {label}
      </span>
      <span style={{ fontSize: 11, color: "var(--muted)" }}>{count > 0 ? count : ""}</span>
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

const pseudoRow: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 8px",
  borderRadius: "var(--radius-sm)",
  cursor: "pointer",
  fontSize: 13,
  userSelect: "none",
  transition: "background var(--anim-fast) var(--ease)",
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

const newFolderButton: React.CSSProperties = {
  marginTop: "var(--space-sm)",
  border: "1px dashed var(--border-strong)",
  background: "transparent",
  color: "var(--muted)",
  borderRadius: "var(--radius-sm)",
  padding: "7px 10px",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  textAlign: "left",
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
