// features/library/DocumentCard.tsx — Une carte de la grille.
//
// Extraite de routes/Home.tsx, augmentée de deux choses : le ruban de
// classification (résumé + mots-clés générés par le LLM) et la source de
// glisser-déposer vers le rail de dossiers.
import { useNavigate } from "react-router-dom";

import { pageImageUrl } from "../../api/client";
import type { DocumentSummary } from "../../api/types";
import { useT } from "../../i18n";
import { DOC_MIME } from "./dnd";
import type { FlatFolder } from "./folderTree";
import { useLibraryUi } from "./useLibraryUi";

const MAX_VISIBLE_KEYWORDS = 3;

export function DocumentCard({
  doc,
  folderName,
  folders,
  onKeyword,
  onMove,
}: {
  doc: DocumentSummary;
  /** Renseigné en mode recherche : le résultat vient peut-être d'un autre dossier. */
  folderName?: string;
  folders: FlatFolder[];
  onKeyword: (keyword: string) => void;
  onMove: (docId: number, folderId: number | null) => void;
}) {
  const navigate = useNavigate();
  const t = useT();
  const dragging = useLibraryUi((s) => s.draggingDocId === doc.id);
  const setDraggingDocId = useLibraryUi((s) => s.setDraggingDocId);

  const progress = doc.page_count > 0 ? Math.round((doc.last_page / doc.page_count) * 100) : 0;
  const pending = doc.digest_status === "pending" && !doc.summary;
  const showRibbon = Boolean(doc.summary) || doc.keywords.length > 0 || pending;

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(DOC_MIME, String(doc.id));
        e.dataTransfer.setData("text/plain", doc.title);
        e.dataTransfer.effectAllowed = "move";
        setDraggingDocId(doc.id);
      }}
      onDragEnd={() => setDraggingDocId(null)}
      onClick={() => navigate(`/reader/${doc.id}`)}
      style={{ ...card, opacity: dragging ? 0.45 : 1 }}
      onMouseEnter={(e) => {
        if (dragging) return;
        e.currentTarget.style.boxShadow = "var(--shadow-md)";
        e.currentTarget.style.transform = "translateY(-2px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = "var(--shadow-sm)";
        e.currentTarget.style.transform = "none";
      }}
    >
      <div style={thumbnail}>
        {doc.extraction_engine === "code" ? (
          // Fichier de code : pas d'image de page → vignette dédiée.
          <div style={codeThumb}>
            <span style={{ fontSize: 34 }}>{"</>"}</span>
            <span style={{ fontSize: 11, padding: "0 10px", textAlign: "center", wordBreak: "break-all" }}>
              {doc.title}
            </span>
          </div>
        ) : (
          <img
            src={pageImageUrl(doc.id, 1, 0.5)}
            alt={doc.title}
            loading="lazy"
            draggable={false}
            style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
          />
        )}

        {showRibbon && (
          <div style={ribbon}>
            {pending ? (
              <div style={pendingText}>{t("library.digest_pending")}</div>
            ) : (
              <>
                {doc.summary && (
                  <div style={ribbonText} title={doc.summary}>
                    {doc.summary}
                  </div>
                )}
                {doc.keywords.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 5 }}>
                    {doc.keywords.slice(0, MAX_VISIBLE_KEYWORDS).map((keyword) => (
                      <button
                        key={keyword}
                        type="button"
                        title={keyword}
                        onClick={(e) => {
                          e.stopPropagation();
                          onKeyword(keyword);
                        }}
                        style={chip}
                      >
                        {keyword}
                      </button>
                    ))}
                    {doc.keywords.length > MAX_VISIBLE_KEYWORDS && (
                      <span style={chipMuted}>
                        {t("library.keywords_more", { n: doc.keywords.length - MAX_VISIBLE_KEYWORDS })}
                      </span>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <div style={{ padding: "var(--space-md)" }}>
        <div style={title} title={doc.title}>
          {doc.title}
        </div>
        <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 4 }}>
          {t("home.pages", { n: doc.page_count })}
          {doc.subject ? ` · ${doc.subject}` : ""}
        </div>
        {folderName && (
          <div style={{ color: "var(--muted-light)", fontSize: 11, marginTop: 3 }}>
            {t("library.in_folder", { name: folderName })}
          </div>
        )}
        <div style={progressTrack}>
          <div style={{ height: "100%", width: `${progress}%`, background: "var(--accent)", borderRadius: 999 }} />
        </div>

        {/* Seul chemin CLAVIER pour ranger un document : le glisser-déposer n'en
            a aucun. Discret au repos, révélé au survol — mais jamais retiré de
            l'arbre d'accessibilité, sinon il ne servirait plus à rien. */}
        <select
          className="card-move"
          aria-label={t("library.move_to")}
          title={t("library.move_to")}
          value={doc.folder_id ?? ""}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
          onChange={(e) => {
            e.stopPropagation();
            const raw = e.target.value;
            onMove(doc.id, raw === "" ? null : Number(raw));
          }}
          style={moveSelect}
        >
          <option value="">{t("library.move_to_root")}</option>
          {/* Indentation par espaces INSÉCABLES : une <option> replie les
              espaces normaux, l'arborescence deviendrait plate. */}
          {folders.map((folder) => (
            <option key={folder.id} value={folder.id}>
              {" ".repeat(folder.depth * 2) + folder.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

const card: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-md)",
  boxShadow: "var(--shadow-sm)",
  overflow: "hidden",
  cursor: "pointer",
  transition: "box-shadow var(--anim-normal) var(--ease), transform var(--anim-normal) var(--ease), opacity var(--anim-fast) var(--ease)",
};

const thumbnail: React.CSSProperties = {
  aspectRatio: "3 / 4",
  background: "var(--bg-alt)",
  overflow: "hidden",
  position: "relative",
};

const codeThumb: React.CSSProperties = {
  width: "100%",
  height: "100%",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  gap: 8,
  background: "var(--surface-soft)",
  color: "var(--muted)",
  fontFamily: "var(--font-mono)",
};

// Ruban translucide : `color-mix` sur --surface le fait suivre le thème, et le
// flou détache le texte de la page rendue en dessous sans la masquer.
const ribbon: React.CSSProperties = {
  position: "absolute",
  left: 0,
  right: 0,
  bottom: 0,
  padding: "8px 10px",
  background: "color-mix(in srgb, var(--surface) 84%, transparent)",
  backdropFilter: "blur(6px)",
  WebkitBackdropFilter: "blur(6px)",
  borderTop: "1px solid var(--border)",
};

const ribbonText: React.CSSProperties = {
  fontSize: 11,
  lineHeight: 1.35,
  color: "var(--text-soft)",
  display: "-webkit-box",
  WebkitLineClamp: 2,
  WebkitBoxOrient: "vertical",
  overflow: "hidden",
};

const pendingText: React.CSSProperties = {
  fontSize: 11,
  color: "var(--muted)",
  fontStyle: "italic",
};

const chip: React.CSSProperties = {
  border: "none",
  background: "var(--accent-soft)",
  color: "var(--accent-hover)",
  borderRadius: 999,
  padding: "2px 7px",
  fontSize: 10,
  fontWeight: 600,
  cursor: "pointer",
  maxWidth: 92,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const chipMuted: React.CSSProperties = {
  ...chip,
  background: "transparent",
  color: "var(--muted)",
  cursor: "default",
};

const title: React.CSSProperties = {
  fontWeight: 600,
  fontSize: 13,
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

// L'effacement au repos (`opacity: 0`) et sa révélation vivent TOUS DEUX dans
// tokens.css (`.card-move`) : un `opacity: 0` inline l'emporterait sur la règle
// de focus, et l'utilisateur clavier tabulerait vers un contrôle resté invisible.
// `opacity` plutôt que `display: none` pour garder l'élément focalisable et
// lisible par un lecteur d'écran.
const moveSelect: React.CSSProperties = {
  marginTop: 8,
  width: "100%",
  font: "inherit",
  fontSize: 11,
  color: "var(--muted)",
  background: "var(--surface-soft)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
  padding: "3px 5px",
  cursor: "pointer",
  transition: "opacity var(--anim-fast) var(--ease)",
};

const progressTrack: React.CSSProperties = {
  height: 6,
  borderRadius: 999,
  background: "var(--border)",
  marginTop: 10,
  overflow: "hidden",
};
