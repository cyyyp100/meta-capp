import { useEffect, useState } from "react";

import { api, pageImageUrl } from "../../api/client";
import type { ReaderBlock } from "../../api/types";
import { useT } from "../../i18n";
import type { TextMark } from "./anchorText";
import { BlockRenderer } from "./blocks/BlockRenderer";

/**
 * Boucle de pages du lecteur RECONSTRUIT (édition cloud) : un div[data-page=n]
 * par page — les contrats du shell Reader restent intacts (IntersectionObserver
 * de page dominante, page verrouillée, ruban marque-page, sélection native via
 * closest("[data-page]")). Une page pas encore OCRisée (reconstruction en
 * cours) retombe sur son image raster : lecture jamais bloquée.
 */

interface Props {
  docId: number;
  pageCount: number;
  /** Largeur cible d'une page (px, déjà multipliée par le zoom). */
  width: number;
  zoom: number;
  currentPage: number;
  renderZoom: number;
  sizes: [number, number][];
  bookmarkPage: number | null;
  locked: boolean;
  lockedPage: number;
  /** Marques par page : citations de Gemma + surlignages mémorisés. */
  marksByPage?: Record<number, TextMark[]>;
  /** Clic sur un <mark data-hl> de surlignage mémorisé. */
  onDeleteHighlight?: (id: number) => void;
}

// undefined = pas encore demandé ; null = pas encore reconstruite (raster).
type BlocksState = Record<number, ReaderBlock[] | null | undefined>;

const PREFETCH_RADIUS = 2;

export function ReconstructedPages({
  docId,
  pageCount,
  width,
  zoom,
  currentPage,
  renderZoom,
  sizes,
  bookmarkPage,
  locked,
  lockedPage,
  marksByPage,
  onDeleteHighlight,
}: Props) {
  const t = useT();
  const [blocksByPage, setBlocksByPage] = useState<BlocksState>({});

  // Suppression d'un surlignage mémorisé : délégation d'événement (les <mark>
  // viennent de dangerouslySetInnerHTML, pas de handler React possible).
  function handleMarkClick(e: React.MouseEvent) {
    const mark = (e.target as HTMLElement).closest("mark[data-hl]");
    if (mark && onDeleteHighlight) {
      const id = Number(mark.getAttribute("data-hl"));
      if (Number.isFinite(id)) onDeleteHighlight(id);
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
        const dimmed = locked && n !== lockedPage;
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
              // Page reconstruite : hauteur au contenu (min ≈ ratio du PDF pour
              // que l'observer et le scroll restent stables avant chargement).
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
                    <BlockRenderer block={block} marks={marksByPage?.[n]} />
                  </div>
                ))}
                <div style={{ textAlign: "right", color: "var(--muted)", fontSize: "0.75em", marginTop: "1.2em" }}>
                  {n}
                </div>
              </div>
            ) : (
              // Page pas (encore) reconstruite : image raster, lecture continue.
              <>
                <img
                  src={pageImageUrl(docId, n, renderZoom)}
                  alt={`Page ${n}`}
                  loading="lazy"
                  draggable={false}
                  style={{
                    width: "100%",
                    height: "100%",
                    display: "block",
                    pointerEvents: "none",
                    userSelect: "none",
                    WebkitUserSelect: "none",
                  }}
                />
                {blocks === null ? (
                  <div
                    style={{
                      position: "absolute",
                      bottom: 10,
                      left: "50%",
                      transform: "translateX(-50%)",
                      padding: "3px 10px",
                      borderRadius: 999,
                      fontSize: 11,
                      background: "color-mix(in srgb, var(--surface) 85%, transparent)",
                      border: "1px solid var(--border)",
                      color: "var(--muted)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {t("reader.ocr_page_pending")}
                  </div>
                ) : null}
              </>
            )}
            {n === bookmarkPage ? (
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
          </div>
        );
      })}
    </>
  );
}
