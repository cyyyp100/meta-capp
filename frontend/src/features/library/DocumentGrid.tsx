// features/library/DocumentGrid.tsx — La grille de cartes et ses états vides.
import { FileText, Plus, SearchX } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import { Button } from "@/components/ui/button";

import type { DocumentSummary } from "../../api/types";
import { useT } from "../../i18n";
import { DocumentCard } from "./DocumentCard";
import type { FlatFolder } from "./folderTree";

export function DocumentGrid({
  documents,
  folderNameOf,
  folders,
  searching,
  query,
  emptyMessage,
  onKeyword,
  onMove,
  onImport,
  importing,
}: {
  documents: DocumentSummary[];
  /** Nom du dossier d'un document — affiché uniquement en mode recherche. */
  folderNameOf: (doc: DocumentSummary) => string | undefined;
  /** Arbre aplati, pour le menu « Déplacer vers… » de chaque carte. */
  folders: FlatFolder[];
  searching: boolean;
  query: string;
  emptyMessage: string;
  onKeyword: (keyword: string) => void;
  onMove: (docId: number, folderId: number | null) => void;
  /** Import depuis l'état vide — le tout premier écran d'un nouvel utilisateur. */
  onImport?: () => void;
  importing?: boolean;
}) {
  const t = useT();
  const reduce = useReducedMotion();

  if (documents.length === 0) {
    // Recherche infructueuse : constat sobre, on ne met pas en scène un échec.
    if (searching) {
      return (
        <div className="mt-10 flex flex-col items-center gap-3 rounded-lg border border-dashed border-border-strong p-12 text-center text-muted-foreground">
          <SearchX className="size-9 text-muted-light" aria-hidden />
          <p className="m-0">{t("library.search_empty", { q: query })}</p>
        </div>
      );
    }

    // Bibliothèque vide : c'est le premier écran de l'application, et le seul
    // endroit de la bibliothèque où un effet marqué se justifie. Le dégradé
    // respire lentement (12 s) — assez lent pour ne jamais accrocher l'œil
    // pendant qu'on lit, assez présent pour que l'écran ne soit pas mort.
    return (
      <div className="relative mt-10 overflow-hidden rounded-lg border border-dashed border-border-strong">
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_60%_at_50%_0%,var(--accent-soft),transparent_70%)]"
          initial={false}
          animate={reduce ? undefined : { opacity: [0.55, 1, 0.55] }}
          transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
        />
        <div className="relative flex flex-col items-center gap-4 p-14 text-center">
          <div className="flex size-14 items-center justify-center rounded-full bg-brand-soft text-brand-ink">
            <FileText className="size-7" aria-hidden />
          </div>
          <p className="m-0 max-w-md text-muted-foreground">{emptyMessage}</p>
          {onImport && (
            <Button onClick={onImport} pending={importing} size="lg">
              {!importing && <Plus className="size-4" aria-hidden />}
              {importing ? t("home.importing") : t("home.import")}
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <>
      {searching && (
        <p className="mt-0 mb-3.5 text-xs text-muted-foreground">
          {t("library.search_results", { n: documents.length, q: query })}
        </p>
      )}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] content-start gap-5.5">
        {documents.map((doc, i) => (
          <motion.div
            key={doc.id}
            // `layout` applique un transform, qui crée un contexte d'empilement :
            // le `z-index: 3` que .doc-card prend au survol resterait prisonnier
            // de cette enveloppe et la carte agrandie passerait SOUS sa voisine.
            // On remonte donc l'élévation ici (cf. l'avertissement de tokens.css).
            className="relative z-0 hover:z-10 focus-within:z-10"
            // Apparition en cascade, plafonnée à 10 cartes : au-delà, l'attente
            // cumulée se verrait plus que l'effet. Le `layout` fait GLISSER les
            // cartes lors d'un filtrage au lieu de les faire sauter.
            layout
            initial={reduce ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.22,
              delay: reduce ? 0 : Math.min(i, 10) * 0.03,
              ease: [0.33, 1, 0.68, 1],
            }}
          >
            <DocumentCard
              doc={doc}
              folderName={searching ? folderNameOf(doc) : undefined}
              folders={folders}
              onKeyword={onKeyword}
              onMove={onMove}
            />
          </motion.div>
        ))}
      </div>
    </>
  );
}
