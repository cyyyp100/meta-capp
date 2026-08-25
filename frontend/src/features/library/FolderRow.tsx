// features/library/FolderRow.tsx — Une ligne du rail : source ET cible de drag.
//
// Le garde-fou anti-cycle est évalué PENDANT le survol (`accepts`) : si le dépôt
// est illégal on n'appelle pas `preventDefault()`, et le navigateur affiche
// nativement le curseur « interdit ». Refuser après le lâcher serait trop tard.
// Le serveur revalide de toute façon (400) : le client fait l'ergonomie, le
// serveur fait la vérité.
import { FolderPlus, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { FolderNode } from "../../api/types";
import { useT } from "../../i18n";
import { IconChevronRight, IconFolder, IconFolderOpen } from "../../components/icons";
import { DOC_MIME, FOLDER_MIME, hasType, readId } from "./dnd";
import { isDescendant, type Selection } from "./folderTree";
import { useLibraryUi } from "./useLibraryUi";

/** Délai de dépliage automatique quand on survole un dossier replié en glissant. */
const HOVER_EXPAND_MS = 700;

export interface FolderRowHandlers {
  onDropDocument: (docId: number, folderId: number | null) => void;
  onDropFolder: (folderId: number, parentId: number | null) => void;
  onRename: (folderId: number, name: string) => void;
  onDelete: (folder: FolderNode) => void;
  onCreateChild: (parentId: number) => void;
}

export function FolderRow({
  folder,
  depth,
  tree,
  selection,
  handlers,
}: {
  folder: FolderNode;
  depth: number;
  tree: FolderNode[];
  selection: Selection;
  handlers: FolderRowHandlers;
}) {
  const t = useT();
  const [over, setOver] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(folder.name);
  const expandTimer = useRef<number | null>(null);

  const expanded = useLibraryUi((s) => s.expanded.includes(folder.id));
  const toggleExpanded = useLibraryUi((s) => s.toggleExpanded);
  const expand = useLibraryUi((s) => s.expand);
  const select = useLibraryUi((s) => s.select);
  const draggingFolderId = useLibraryUi((s) => s.draggingFolderId);
  const setDraggingFolderId = useLibraryUi((s) => s.setDraggingFolderId);

  const active = selection.kind === "folder" && selection.id === folder.id;
  const hasChildren = folder.children.length > 0;

  useEffect(() => () => {
    if (expandTimer.current !== null) window.clearTimeout(expandTimer.current);
  }, []);

  /** Ce dépôt est-il légal ? Évalué au survol, d'où la lecture des TYPES seuls. */
  function accepts(dt: DataTransfer): boolean {
    if (hasType(dt, DOC_MIME)) return true;
    if (!hasType(dt, FOLDER_MIME) || draggingFolderId === null) return false;
    // `dataTransfer.getData()` est illisible ici : l'id vient du store.
    return !isDescendant(tree, folder.id, draggingFolderId);
  }

  function armAutoExpand() {
    if (expanded || !hasChildren || expandTimer.current !== null) return;
    expandTimer.current = window.setTimeout(() => {
      expand([folder.id]);
      expandTimer.current = null;
    }, HOVER_EXPAND_MS);
  }

  function cancelAutoExpand() {
    if (expandTimer.current === null) return;
    window.clearTimeout(expandTimer.current);
    expandTimer.current = null;
  }

  function commitRename() {
    setRenaming(false);
    const name = draft.trim();
    if (name && name !== folder.name) handlers.onRename(folder.id, name);
    else setDraft(folder.name);
  }

  return (
    <>
      <div
        role="treeitem"
        aria-expanded={hasChildren ? expanded : undefined}
        aria-selected={active}
        tabIndex={0}
        draggable={!renaming}
        onDragStart={(e) => {
          e.stopPropagation();
          e.dataTransfer.setData(FOLDER_MIME, String(folder.id));
          e.dataTransfer.effectAllowed = "move";
          setDraggingFolderId(folder.id);
        }}
        onDragEnd={() => {
          setDraggingFolderId(null);
          cancelAutoExpand();
          setOver(false);
        }}
        onDragEnter={(e) => {
          if (!accepts(e.dataTransfer)) return;
          e.preventDefault();
          setOver(true);
          armAutoExpand();
        }}
        onDragOver={(e) => {
          // `preventDefault` est requis à CHAQUE dragover, pas seulement au premier.
          if (!accepts(e.dataTransfer)) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
        }}
        onDragLeave={(e) => {
          // Un enfant du div déclenche `dragleave` sur le parent : sans ce test,
          // la surbrillance clignote à chaque pixel parcouru.
          if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
          setOver(false);
          cancelAutoExpand();
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation(); // sinon une ligne imbriquée traiterait le dépôt deux fois
          setOver(false);
          cancelAutoExpand();
          const docId = readId(e.dataTransfer, DOC_MIME);
          if (docId !== null) {
            handlers.onDropDocument(docId, folder.id);
            return;
          }
          const movedId = readId(e.dataTransfer, FOLDER_MIME);
          if (movedId !== null) handlers.onDropFolder(movedId, folder.id);
        }}
        onClick={() => select({ kind: "folder", id: folder.id })}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            select({ kind: "folder", id: folder.id });
          } else if (e.key === "ArrowRight" && hasChildren && !expanded) {
            toggleExpanded(folder.id);
          } else if (e.key === "ArrowLeft" && hasChildren && expanded) {
            toggleExpanded(folder.id);
          } else if (e.key === "F2") {
            setRenaming(true);
          }
        }}
        style={{
          ...row,
          paddingLeft: 8 + depth * 14,
          background: over ? "var(--accent-soft)" : active ? "var(--accent-soft)" : "transparent",
          color: over || active ? "var(--accent-hover)" : "var(--text-soft)",
          outline: over ? "2px solid var(--accent)" : "2px solid transparent",
          outlineOffset: -2,
        }}
      >
        <button
          type="button"
          aria-hidden={!hasChildren}
          tabIndex={-1}
          onClick={(e) => {
            e.stopPropagation();
            if (hasChildren) toggleExpanded(folder.id);
          }}
          style={{
            ...chevron,
            visibility: hasChildren ? "visible" : "hidden",
            transform: expanded ? "rotate(90deg)" : "none",
          }}
        >
          <IconChevronRight size={13} />
        </button>

        {expanded && hasChildren ? <IconFolderOpen size={15} /> : <IconFolder size={15} />}

        {renaming ? (
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            onBlur={commitRename}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setDraft(folder.name);
                setRenaming(false);
              }
            }}
            style={renameInput}
          />
        ) : (
          <span style={label} title={folder.name}>
            {folder.name}
          </span>
        )}

        {!renaming && (
          <>
            <span style={count}>{folder.total_count > 0 ? folder.total_count : ""}</span>
            <span className="folder-actions" style={actions}>
              <button
                type="button"
                title={t("library.new_subfolder")}
                aria-label={t("library.new_subfolder")}
                onClick={(e) => {
                  e.stopPropagation();
                  handlers.onCreateChild(folder.id);
                }}
                className={actionButton}
              >
                <FolderPlus className="size-3.5" aria-hidden />
              </button>
              <button
                type="button"
                title={t("library.rename")}
                aria-label={t("library.rename")}
                onClick={(e) => {
                  e.stopPropagation();
                  setDraft(folder.name);
                  setRenaming(true);
                }}
                className={actionButton}
              >
                <Pencil className="size-3.5" aria-hidden />
              </button>
              <button
                type="button"
                title={t("library.delete")}
                aria-label={t("library.delete")}
                onClick={(e) => {
                  e.stopPropagation();
                  handlers.onDelete(folder);
                }}
                className={actionButton}
              >
                <Trash2 className="size-3.5" aria-hidden />
              </button>
            </span>
          </>
        )}
      </div>

      {expanded &&
        folder.children.map((child) => (
          <FolderRow
            key={child.id}
            folder={child}
            depth={depth + 1}
            tree={tree}
            selection={selection}
            handlers={handlers}
          />
        ))}
    </>
  );
}

const row: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  padding: "6px 8px",
  borderRadius: "var(--radius-sm)",
  cursor: "pointer",
  fontSize: 13,
  userSelect: "none",
  transition: "background var(--anim-fast) var(--ease)",
};

const chevron: React.CSSProperties = {
  border: "none",
  background: "transparent",
  color: "inherit",
  padding: 0,
  display: "flex",
  cursor: "pointer",
  transition: "transform var(--anim-fast) var(--ease)",
};

const label: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const count: React.CSSProperties = {
  fontSize: 11,
  color: "var(--muted)",
  minWidth: 14,
  textAlign: "right",
};

const actions: React.CSSProperties = {
  display: "flex",
  gap: 2,
  opacity: 0,
  transition: "opacity var(--anim-fast) var(--ease)",
};

const actionButton =
  "flex rounded-[4px] border-none bg-transparent p-[2px_3px] leading-none text-muted-foreground " +
  "transition-colors duration-fast ease-brand " +
  "hover:bg-accent hover:text-accent-foreground " +
  "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none";

const renameInput: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  font: "inherit",
  padding: "2px 6px",
  border: "1px solid var(--accent)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface)",
  color: "var(--text)",
};
