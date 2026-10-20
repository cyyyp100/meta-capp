import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { AnnotationLabel, ReaderBlock, ReaderNote } from "../../api/types";
import { useT } from "../../i18n";
import type { TextMark } from "./anchorText";
import { PageNotesLayer } from "./annotations/PageNotesLayer";
import { BlockRenderer } from "./blocks/BlockRenderer";
import { PageBookmarkButton } from "./PageBookmarkButton";

/**
 * Boucle de pages du lecteur en BLOCS DE TEXTE — les fichiers de code, seuls
 * documents paginés en blocs dans cette édition (les PDF sont rendus en images
 * par le lecteur raster). Un div[data-page=n] par page : les contrats du shell
 * Reader restent intacts (IntersectionObserver de page dominante, page
 * verrouillée, ruban de la dernière position, marque-page, post-it et
 * signets, sélection native via closest("[data-page]")).
 *
 * Les blocs ne sont chargés qu'autour de la page courante (PREFETCH_RADIUS) :
 * une page pas encore chargée affiche un cadre vide au bon ratio, ce qui garde
 * le scroll et l'observer stables sans rien demander au serveur.
 */

interface Props {
  docId: number;
  pageCount: number;
  /** Largeur cible d'une page (px, déjà multipliée par le zoom). */
  width: number;
  zoom: number;
  currentPage: number;
  sizes: [number, number][];
  /** Page quittée à la dernière séance (ruban), nulle quand un marque-page existe. */
  lastPositionPage: number | null;
  /** Page du marque-page de l'élève. */
  bookmarkPage: number | null;
  /** Pose ou retire le marque-page ; absent, pas de bouton (visite guidée). */
  onToggleBookmark?: (page: number) => void;
  locked: boolean;
  lockedPage: number;
  /** Marques par page : citations de Clikoda + surlignages mémorisés. */
  marksByPage?: Record<number, TextMark[]>;
  /** Clic sur un <mark data-hl> de surlignage mémorisé : son édition. */
  onEditHighlight?: (id: number) => void;
  /** Post-it (sans géométrie : empilés dans la marge) et signets, par page. */
  notesByPage?: Record<number, ReaderNote[]>;
  labelsById?: Map<number, AnnotationLabel>;
  /** Absent : post-it et signets en lecture seule (visite guidée). */
  onEditNote?: (id: number) => void;
  /** Post-it ou signet que le carnet vient de désigner (« n-3 ») : il clignote. */
  flash?: string | null;
  /** Occurrences de la recherche par page : plages UTF-16 dans le texte du
   *  bloc de code de la page (un seul bloc par page de code). */
  findRangesByPage?: Record<number, [number, number][]>;
  /** L'occurrence courante : sa page et son rang sur la page. */
  findCurrent?: { page: number; index: number } | null;
}

// undefined = pas encore demandé ; null = le serveur n'a pas de blocs pour
// cette page (ne se produit pas pour un fichier de code, mais l'API le permet).
type BlocksState = Record<number, ReaderBlock[] | null | undefined>;

const PREFETCH_RADIUS = 2;

export function BlockPages({
  docId,
  pageCount,
  width,
  zoom,
  currentPage,
  sizes,
  lastPositionPage,
  bookmarkPage,
  onToggleBookmark,
  locked,
  lockedPage,
  marksByPage,
  onEditHighlight,
  notesByPage,
  labelsById,
  onEditNote,
  flash = null,
  findRangesByPage,
  findCurrent = null,
}: Props) {
  const t = useT();
  const [blocksByPage, setBlocksByPage] = useState<BlocksState>({});

  // Édition d'un surlignage mémorisé : délégation d'événement (les <mark>
  // viennent de dangerouslySetInnerHTML, pas de handler React possible).
  function handleMarkClick(e: React.MouseEvent) {
    const mark = (e.target as HTMLElement).closest("mark[data-hl]");
    if (mark && onEditHighlight) {
      const id = Number(mark.getAttribute("data-hl"));
      if (Number.isFinite(id)) onEditHighlight(id);
    }
  }

  // Blocs de la page dominante + voisines (même politique que le calque de mots).
  useEffect(() => {
    let cancelled = false;
    const wanted = [];
    for (let p = currentPage - PREFETCH_RADIUS; p <= currentPage + PREFETCH_RADIUS; p++) {
      if (p >= 1 && p <= pageCount && blocksByPage[p] === undefined) wanted.push(p);
    }
    for (const p of wanted) {
      api
        .pageBlocks(docId, p)
        .then(({ blocks }) => {
          if (!cancelled) setBlocksByPage((prev) => (prev[p] !== undefined ? prev : { ...prev, [p]: blocks }));
        })
        .catch(() => {});
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId, currentPage, pageCount]);

  return (
    <>
      {Array.from({ length: pageCount }, (_, i) => i + 1).map((n) => {
        const blocks = blocksByPage[n];
        const [w, h] = sizes[n - 1] ?? [595, 842];
        // Même règle que les pages PDF : les pages au-dessus de la page bloquée se relisent.
        const dimmed = locked && n > lockedPage;
        const visible = (blocks ?? []).filter((b) => !b.metadata?.reader_hidden);
        return (
          <div
            key={n}
            data-page={n}
            style={{
              position: "relative",
              width,
              background: "var(--surface)",
              boxShadow: "var(--shadow-md)",
              borderRadius: 4,
              cursor: "default",
              opacity: dimmed ? 0.3 : 1,
              transition: "opacity 0.2s",
              // Page chargée : hauteur au contenu. Sinon on garde le ratio de
              // page pour que l'observer et le scroll restent stables.
              ...(blocks && visible.length
                ? { minHeight: width * 0.3 }
                : { aspectRatio: `${w} / ${h}` }),
            }}
          >
            {blocks && visible.length ? (
              <div
                onClick={handleMarkClick}
                style={{
                  padding: `${Math.round(width * 0.07)}px ${Math.round(width * 0.09)}px`,
                  fontSize: 16 * zoom,
                  color: "var(--text)",
                  userSelect: "text",
                  WebkitUserSelect: "text",
                  cursor: "text",
                }}
              >
                {visible.map((block) => (
                  <div key={block.id} data-block-id={block.id}>
                    <BlockRenderer
                      block={block}
                      marks={marksByPage?.[n]}
                      findRanges={block.type === "code" ? findRangesByPage?.[n] : undefined}
                      findCurrent={findCurrent?.page === n ? findCurrent.index : -1}
                    />
                  </div>
                ))}
                <div style={{ textAlign: "right", color: "var(--muted)", fontSize: "0.75em", marginTop: "1.2em" }}>
                  {n}
                </div>
              </div>
            ) : (
              // Blocs pas encore chargés : cadre vide au ratio de la page. Ne
              // JAMAIS retomber sur <img src={pageImageUrl(...)}> ici — un
              // document code n'a pas d'image de page (render_page renvoie None,
              // l'endpoint .png répond 404), donc chaque page hors fenêtre de
              // préchargement déclencherait une requête en échec.
              <div style={{ width: "100%", height: "100%" }} />
            )}
            {n === lastPositionPage ? (
              <div
                title={t("reader.last_position")}
                style={{
                  position: "absolute",
                  top: 24,
                  right: 0,
                  width: 10,
                  height: 46,
                  background: "var(--accent)",
                  borderRadius: "3px 0 0 3px",
                  boxShadow: "var(--shadow-sm)",
                  zIndex: 5,
                }}
              />
            ) : null}
            {notesByPage?.[n] && labelsById ? (
              <PageNotesLayer
                notes={notesByPage[n]}
                labelsById={labelsById}
                scale={null}
                flashId={flash?.startsWith("n-") ? Number(flash.slice(2)) : null}
                onEdit={onEditNote}
              />
            ) : null}
            {onToggleBookmark ? (
              <PageBookmarkButton page={n} active={n === bookmarkPage} onToggle={onToggleBookmark} />
            ) : null}
          </div>
        );
      })}
    </>
  );
}
