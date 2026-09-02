import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Flame, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import { api } from "../api/client";
import { pickFilePath } from "../api/platform";
import type { DocumentSummary, FolderNode } from "../api/types";
import { DocumentGrid } from "../features/library/DocumentGrid";
import { FolderRail } from "../features/library/FolderRail";
import type { FolderRowHandlers } from "../features/library/FolderRow";
import { ancestorIds, findFolder, flattenFolders } from "../features/library/folderTree";
import { ResumeCard } from "../features/library/ResumeCard";
import { SearchBox } from "../features/library/SearchBox";
import { useDebounced } from "../features/library/useDebounced";
import { useLibraryUi } from "../features/library/useLibraryUi";
import { useT } from "../i18n";
import { useTour } from "../features/tour/useTour";

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
  const confirm = useConfirm();
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
      // Un `alert()` bloquait la fenêtre et s'annonçait « 127.0.0.1:8756 indique ».
      toast.error(t("library.import_error", { message: String((e as Error).message) }));
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
      toast.error((e as Error).message || t(fallbackKey));
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
    onDelete: async (folder: FolderNode) => {
      const ok = await confirm({
        title: t("library.folder_delete_title", { name: folder.name }),
        description: t("library.folder_delete_confirm"),
        confirmLabel: t("common.delete"),
        destructive: true,
      });
      if (!ok) return;
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

  // Étape 1 de la visite : le bouton d'import, sur l'écran qu'on a vraiment
  // sous les yeux au premier lancement — une bibliothèque vide.
  const requestTour = useTour((s) => s.request);
  useEffect(() => {
    if (documents) requestTour("import");
  }, [documents, requestTour]);

  const emptyMessage =
    selection.kind === "folder" && !searching ? t("library.folder_empty_docs") : t("home.empty");

  return (
    <div style={page}>
      <div style={header}>
        <div>
          <div className="flex items-center gap-3">
            <h1 className="m-0 font-serif text-h1 font-bold">
              {t("home.title")}
            </h1>
            {streak && streak.streak > 0 && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge
                    variant="outline"
                    // La flamme prend la MARQUE et non `--warning` : une série
                    // en cours est une progression, pas une alerte. Elle
                    // empruntait l'or de l'avertissement du temps où les deux
                    // se ressemblaient ; `--warning` est violet désormais, et
                    // une flamme violette ne veut rien dire.
                    className="gap-1 border-brand/30 bg-brand-soft font-bold text-brand-ink"
                  >
                    <Flame className="size-3.5" aria-hidden />
                    {streak.streak}
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>
                  {t("home.streak", { n: streak.streak })} · {t("streak.grace")}
                </TooltipContent>
              </Tooltip>
            )}
          </div>
          <p className="mt-1 mb-0 text-muted-foreground">{t("home.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <SearchBox value={rawQuery} onChange={setRawQuery} />
          <Button data-tour="import" onClick={handleImport} pending={importing}>
            {!importing && <Plus className="size-4" aria-hidden />}
            {importing ? t("home.importing") : t("home.import")}
          </Button>
        </div>
      </div>

      {/* La grille sautait d'un « Chargement… » d'une ligne à un mur de cartes.
          La silhouette réserve exactement la place que prendra le contenu. */}
      {isLoading && (
        <div style={body} role="status" aria-busy="true">
          <span className="sr-only">{t("common.loading")}</span>
          <Skeleton className="h-72 w-56 shrink-0 rounded-lg" />
          <div className="grid flex-1 auto-rows-min grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-5.5">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-52 rounded-lg" />
            ))}
          </div>
        </div>
      )}

      {isError && (
        <div className="mt-5.5 flex flex-col items-start gap-3 rounded-md border border-danger/30 bg-danger-soft p-5.5">
          <p className="m-0 font-semibold text-danger">{t("home.error")}</p>
          <Button variant="secondary" size="sm" onClick={() => void refreshLibrary()}>
            {t("common.retry")}
          </Button>
        </div>
      )}

      {/* La reprise passe AVANT la grille : c'est le geste que quelqu'un qui
          revient veut faire, et le seul qui n'exige aucune décision. Elle
          disparaît en recherche — on cherche alors autre chose que la suite. */}
      {documents && documents.length > 0 && !searching && selection.kind !== "folder" && (
        <div className="mt-5.5">
          <ResumeCard documents={allDocuments} />
        </div>
      )}

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
              // L'état vide porte lui-même l'appel à l'import : c'est le premier
              // écran d'un nouvel utilisateur, le bouton du bandeau est loin.
              onImport={selection.kind === "all" ? handleImport : undefined}
              importing={importing}
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

