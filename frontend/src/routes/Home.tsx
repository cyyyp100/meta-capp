import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { pickFilePath } from "../api/platform";
import type { DocumentSummary, FolderNode } from "../api/types";
import { DocumentGrid } from "../features/library/DocumentGrid";
import { FolderRail } from "../features/library/FolderRail";
import type { FolderRowHandlers } from "../features/library/FolderRow";
import { ancestorIds, findFolder, flattenFolders } from "../features/library/folderTree";
import { SearchBox } from "../features/library/SearchBox";
import { useDebounced } from "../features/library/useDebounced";
import { useLibraryUi } from "../features/library/useLibraryUi";
import { useT } from "../i18n";

/** Nombre de documents de l'entrée « Récents » (le catalogue est déjà trié). */
const RECENT_COUNT = 12;
/** En dessous de 2 caractères, une recherche ramènerait toute la bibliothèque. */
const MIN_QUERY_LENGTH = 2;
/** Cadence de relance tant qu'une fiche LLM est en cours de génération. */
const DIGEST_POLL_MS = 4000;

export function Home() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const t = useT();
  const [importing, setImporting] = useState(false);
  const [rawQuery, setRawQuery] = useState("");

  const query = useDebounced(rawQuery, 250).trim();
  const searching = query.length >= MIN_QUERY_LENGTH;

  const selection = useLibraryUi((s) => s.selection);
  const select = useLibraryUi((s) => s.select);
  const expand = useLibraryUi((s) => s.expand);

  const { data: documents, isLoading, isError } = useQuery({
    queryKey: ["library", "documents"],
    queryFn: api.libraryDocuments,
    // La fiche LLM arrive APRÈS la réponse d'import (file LLM sérialisée) : on
    // relance tant qu'un document visible attend la sienne, puis on s'arrête.
    refetchInterval: (q) =>
      (q.state.data ?? []).some((d) => d.digest_status === "pending") ? DIGEST_POLL_MS : false,
  });
  const { data: folders } = useQuery({ queryKey: ["library", "folders"], queryFn: api.folders });
  const { data: results } = useQuery({
    queryKey: ["library", "search", query],
    queryFn: () => api.searchDocuments(query),
    enabled: searching,
    placeholderData: keepPreviousData,
  });
  const { data: streak } = useQuery({ queryKey: ["streak"], queryFn: api.streak });

  const tree = useMemo(() => folders ?? [], [folders]);
  const allDocuments = useMemo(() => documents ?? [], [documents]);

  // Arbre aplati : sert au menu « Déplacer vers… » des cartes et à retrouver le
  // nom d'un dossier depuis son id.
  const flatFolders = useMemo(() => flattenFolders(tree), [tree]);
  const folderNames = useMemo(() => {
    const map = new Map<number, string>();
    for (const folder of flatFolders) map.set(folder.id, folder.name);
    return map;
  }, [flatFolders]);

  const visible = useMemo(() => {
    if (searching) return results ?? [];
    switch (selection.kind) {
      case "recent":
        return allDocuments.slice(0, RECENT_COUNT);
      case "unfiled":
        return allDocuments.filter((d) => d.folder_id === null);
      case "folder":
        return allDocuments.filter((d) => d.folder_id === selection.id);
      default:
        return allDocuments;
    }
  }, [searching, results, selection, allDocuments]);

  const counts = useMemo(
    () => ({
      all: allDocuments.length,
      recent: Math.min(allDocuments.length, RECENT_COUNT),
      unfiled: allDocuments.filter((d) => d.folder_id === null).length,
    }),
    [allDocuments],
  );

  async function refreshLibrary() {
    // React Query compare les clés par préfixe : un seul appel rafraîchit le
    // catalogue, l'arbre et la recherche en cours.
    await queryClient.invalidateQueries({ queryKey: ["library"] });
  }

  async function handleImport() {
    if (importing) return;
    const path = await pickFilePath();
    if (!path) return;
    setImporting(true);
    try {
      const doc = await api.importPdf(path);
      await refreshLibrary();
      navigate(`/reader/${doc.id}`);
    } catch (e) {
      alert(t("library.import_error", { message: String((e as Error).message) }));
    } finally {
      setImporting(false);
    }
  }

  /** Une mutation de rangement : on rejoue la lecture, on signale les refus. */
  async function mutate(action: () => Promise<unknown>, fallbackKey: string) {
    try {
      await action();
      await refreshLibrary();
    } catch (e) {
      // Le serveur renvoie un `detail` déjà traduit (garde-fou de cycle…).
      alert((e as Error).message || t(fallbackKey));
    }
  }

  const handlers: FolderRowHandlers = {
    onDropDocument: (docId, folderId) =>
      void mutate(() => api.moveDocument(docId, folderId), "library.move_error"),
    onDropFolder: (folderId, parentId) =>
      void mutate(() => api.moveFolder(folderId, parentId), "library.move_error"),
    onRename: (folderId, name) =>
      void mutate(() => api.renameFolder(folderId, name), "library.folder_error"),
    onCreateChild: (parentId) =>
      void mutate(async () => {
        const created = await api.createFolder(t("library.new_subfolder"), parentId);
        // Déplier la chaîne d'ancêtres, sinon le dossier créé reste invisible.
        expand([...ancestorIds(tree, parentId), parentId]);
        return created;
      }, "library.folder_error"),
    onDelete: (folder: FolderNode) => {
      if (!window.confirm(t("library.folder_delete_confirm", { name: folder.name }))) return;
      void mutate(async () => {
        await api.deleteFolder(folder.id);
        // La sélection pointait peut-être sur le dossier supprimé.
        if (selection.kind === "folder" && findFolder(tree, selection.id)) {
          const gone = selection.id === folder.id;
          if (gone) select({ kind: "all" });
        }
      }, "library.folder_error");
    },
  };

  const emptyMessage =
    selection.kind === "folder" && !searching ? t("library.folder_empty_docs") : t("home.empty");

  return (
    <div style={page}>
      <div style={header}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h1 style={{ fontFamily: "var(--font-title)", fontSize: 32, margin: "0 0 4px" }}>
              {t("home.title")}
            </h1>
            {streak && streak.streak > 0 && (
              <span title="Jours consécutifs" style={streakPill}>
                🔥 {streak.streak}
              </span>
            )}
          </div>
          <p style={{ color: "var(--muted)", marginTop: 0 }}>{t("home.subtitle")}</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-sm)" }}>
          <SearchBox value={rawQuery} onChange={setRawQuery} />
          <button onClick={handleImport} disabled={importing} style={importButton(importing)}>
            {importing ? t("home.importing") : t("home.import")}
          </button>
        </div>
      </div>

      {isLoading && <p style={{ color: "var(--muted)" }}>{t("common.loading")}</p>}
      {isError && <p style={{ color: "var(--danger)" }}>{t("home.error")}</p>}

      {documents && (
        <div style={body}>
          <FolderRail
            tree={tree}
            counts={counts}
            handlers={handlers}
            onCreateRoot={(name) =>
              void mutate(() => api.createFolder(name, null), "library.folder_error")
            }
          />
          <main style={main}>
            <DocumentGrid
              documents={visible}
              folderNameOf={(doc: DocumentSummary) =>
                doc.folder_id === null ? undefined : folderNames.get(doc.folder_id)
              }
              folders={flatFolders}
              searching={searching}
              query={query}
              emptyMessage={emptyMessage}
              onKeyword={setRawQuery}
              onMove={handlers.onDropDocument}
            />
          </main>
        </div>
      )}
    </div>
  );
}

const page: React.CSSProperties = {
  height: "100%",
  display: "flex",
  flexDirection: "column",
  minHeight: 0,
  padding: "var(--space-xl)",
};

const header: React.CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  gap: 16,
  flexWrap: "wrap",
};

const body: React.CSSProperties = {
  display: "flex",
  gap: "var(--space-lg)",
  flex: 1,
  minHeight: 0,
  marginTop: "var(--space-lg)",
};

const main: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  overflowY: "auto",
  // `overflowY: auto` rend aussi l'axe horizontal scrollable : sans cette marge,
  // une carte agrandie au survol serait rognée sur les bords de la grille.
  padding: "8px 6px",
};

const streakPill: React.CSSProperties = {
  background: "var(--warning-soft)",
  color: "var(--warning)",
  fontWeight: 700,
  fontSize: 13,
  padding: "4px 10px",
  borderRadius: 999,
};

function importButton(importing: boolean): React.CSSProperties {
  return {
    border: "none",
    background: "var(--accent)",
    color: "#fff",
    borderRadius: "var(--radius-sm)",
    padding: "10px 18px",
    fontWeight: 600,
    cursor: importing ? "default" : "pointer",
    whiteSpace: "nowrap",
    boxShadow: "var(--shadow-sm)",
  };
}
