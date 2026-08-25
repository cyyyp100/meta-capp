// features/library/DocumentGrid.tsx — La grille de cartes et ses états vides.
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
}) {
  const t = useT();

  if (documents.length === 0) {
    return (
      <div style={empty}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>{searching ? "🔍" : "📄"}</div>
        {searching ? t("library.search_empty", { q: query }) : emptyMessage}
      </div>
    );
  }

  return (
    <>
      {searching && (
        <p style={resultsHeader}>{t("library.search_results", { n: documents.length, q: query })}</p>
      )}
      <div style={grid}>
        {documents.map((doc) => (
          <DocumentCard
            key={doc.id}
            doc={doc}
            folderName={searching ? folderNameOf(doc) : undefined}
            folders={folders}
            onKeyword={onKeyword}
            onMove={onMove}
          />
        ))}
      </div>
    </>
  );
}

const grid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
  gap: "var(--space-lg)",
  alignContent: "start",
};

const empty: React.CSSProperties = {
  marginTop: 40,
  padding: 48,
  textAlign: "center",
  border: "1px dashed var(--border-strong)",
  borderRadius: "var(--radius-lg)",
  color: "var(--muted)",
};

const resultsHeader: React.CSSProperties = {
  margin: "0 0 var(--space-md)",
  fontSize: 12,
  color: "var(--muted)",
};
