import { memo, useEffect, useRef, useState } from "react";

import { pageImageUrl } from "../../api/client";
import type { PageWord } from "../../api/types";
import { useT } from "../../i18n";
import { PageBookmarkButton } from "./PageBookmarkButton";
import { PageTextLayer } from "./PageTextLayer";

/** Marge (en points PDF) autour du passage cité, pour le liseré de la zone. */
export const ZONE_PAD_PTS = 4;
// Marge du cache de rappel libre : couvre jambages et interlignes, sinon les
// hampes des lignes voisines laissent deviner le passage.
const MASK_PAD_PTS = 2.5;

/** Surlignage mémorisé d'une page, prêt à dessiner (rects fusionnés par ligne, couleur résolue). */
export interface SavedPageHighlight {
  id: number;
  fill: string;
  rects: number[][];
}

/**
 * Boîte englobante des surlignages d'une page, en pixels d'écran.
 *
 * Sert d'ancre à l'étape de la visite qui explique « elle surligne le passage
 * dont elle parle » : le voile éclaire ce rectangle en même temps que la
 * réponse de Clikoda. Sans lui, l'étape désignait le panneau et laissait le
 * passage cité dans le noir — exactement ce qu'elle demande de regarder.
 */
function highlightBounds(groups: { rect: number[] }[], scale: number) {
  const left = Math.min(...groups.map((g) => g.rect[0]));
  const top = Math.min(...groups.map((g) => g.rect[1]));
  const right = Math.max(...groups.map((g) => g.rect[2]));
  const bottom = Math.max(...groups.map((g) => g.rect[3]));
  return {
    left: left * scale,
    top: top * scale,
    width: (right - left) * scale,
    height: (bottom - top) * scale,
  };
}

interface Props {
  docId: number;
  page: number;
  /** Largeur de la page à l'écran (px, zoom compris). */
  width: number;
  /** Taille de la page en points PDF. */
  widthPts: number;
  heightPts: number;
  /** Résolution de l'image demandée au serveur (palier, cf. Reader). */
  renderZoom: number;
  contentHash: string | null;
  dimmed: boolean;
  /** Page quittée à la dernière séance : ruban sur le bord droit (sans marque-page seulement). */
  lastPosition: boolean;
  /** Le marque-page de l'élève est sur cette page. */
  bookmarked: boolean;
  /** Passages cités par Clikoda sur cette page. */
  highlights?: { rect: number[]; color: string }[];
  /** Zone visée par la question en cours, si elle est sur cette page. */
  zoneRect: number[] | null;
  /** Cache du rappel libre, si le passage est sur cette page. */
  mask?: number[][];
  /** Mots du calque de texte (chargés autour de la page dominante). */
  words?: PageWord[];
  saved: SavedPageHighlight[];
  /** Occurrences de la recherche (Ctrl/Cmd+F) sur cette page : une liste de
   *  rects par occurrence. `NO_HITS` hors recherche — une liste stable. */
  findHits?: number[][][];
  /** Rang, sur cette page, de l'occurrence courante ; -1 si elle est ailleurs. */
  findCurrent?: number;
  demo: boolean;
  onDeleteHighlight: (id: number) => void;
  /** Pose ou retire le marque-page ; absent, pas de bouton (visite guidée). */
  onToggleBookmark?: (page: number) => void;
}

/** Aucune occurrence : la même liste à chaque rendu (la page est mémoïsée). */
export const NO_HITS: number[][][] = [];

/**
 * Une page PDF du lecteur : image, surlignages, zone, cache, calque de texte,
 * ruban de la dernière position, bouton du marque-page.
 *
 * Mémoïsée, et ses props sont stables d'un rendu à l'autre : le lecteur se
 * re-rend à chaque page dominante qui change en cours de défilement, à chaque
 * arrivée de mots, à chaque pas de zoom — toutes les pages se redessinaient
 * avec lui. Seule la page dont quelque chose a changé se redessine maintenant.
 */
export const PdfPage = memo(function PdfPage({
  docId,
  page,
  width,
  widthPts: w,
  heightPts: h,
  renderZoom,
  contentHash,
  dimmed,
  lastPosition,
  bookmarked,
  highlights,
  zoneRect,
  mask,
  words,
  saved,
  findHits = NO_HITS,
  findCurrent = -1,
  demo,
  onDeleteHighlight,
  onToggleBookmark,
}: Props) {
  const t = useT();
  const scale = width / w;
  const src = pageImageUrl(docId, page, renderZoom, contentHash);
  // L'image affichée reste celle qu'on a tant que la nouvelle résolution n'est
  // pas chargée ET décodée : changer `src` directement vidait la page le temps
  // du chargement, un flash blanc à chaque palier de zoom.
  const [shown, setShown] = useState(src);
  // Seule une page déjà chargée précharge : une page encore hors de vue garde
  // son chargement paresseux (`loading="lazy"`), elle prend la nouvelle adresse.
  const loadedRef = useRef(false);
  useEffect(() => {
    if (src === shown) return;
    if (!loadedRef.current) {
      setShown(src);
      return;
    }
    let cancelled = false;
    const next = new Image();
    next.src = src;
    next.decode().then(
      () => {
        if (!cancelled) setShown(src);
      },
      () => {
        /* nouvelle résolution indisponible : la page garde son image */
      },
    );
    return () => {
      cancelled = true;
    };
    // `shown` n'est pas une dépendance : seule une nouvelle adresse déclenche.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);

  return (
    <div
      data-page={page}
      // Ancre de la visite guidée, sur la PREMIÈRE page seulement :
      // `querySelector` prend le premier élément trouvé, donc la
      // poser sur toutes reviendrait au même — mais dire « la page
      // 1 » ici évite qu'on croie l'attribut générique et qu'on
      // s'appuie dessus ailleurs.
      {...(page === 1 ? { "data-tour": "page" } : {})}
      style={{
        position: "relative",
        width,
        aspectRatio: `${w} / ${h}`,
        background: "var(--surface)",
        boxShadow: "var(--shadow-md)",
        borderRadius: 4,
        overflow: "hidden",
        cursor: "default",
        opacity: dimmed ? 0.3 : 1,
        transition: "opacity 0.2s",
      }}
    >
      <img
        src={shown}
        alt={`Page ${page}`}
        loading="lazy"
        decoding="async"
        draggable={false}
        onLoad={() => {
          loadedRef.current = true;
        }}
        style={{
          width: "100%",
          height: "100%",
          display: "block",
          // L'image ne doit jamais capter le drag de sélection (WebKit/pywebview).
          pointerEvents: "none",
          userSelect: "none",
          WebkitUserSelect: "none",
        }}
      />
      {/* Dernière position : ruban sur le bord droit de la page quittée la dernière fois. */}
      {lastPosition ? (
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
      {highlights?.length ? (
        <svg
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
        >
          {highlights.map((g, gi) => (
            <rect
              key={gi}
              x={g.rect[0]}
              y={g.rect[1]}
              width={g.rect[2] - g.rect[0]}
              height={g.rect[3] - g.rect[1]}
              fill={g.color}
              opacity={0.35}
              rx={1}
            />
          ))}
        </svg>
      ) : null}
      {/* Zone visée par la question en cours : un liseré à l'accent,
          pour qu'on voie de quoi Clikoda parle — surtout quand la
          lecture est bloquée dessus. */}
      {zoneRect ? (
        <svg
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          aria-hidden
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 4 }}
        >
          <rect
            data-testid="question-zone"
            x={zoneRect[0] - ZONE_PAD_PTS}
            y={zoneRect[1] - ZONE_PAD_PTS}
            width={zoneRect[2] - zoneRect[0] + 2 * ZONE_PAD_PTS}
            height={zoneRect[3] - zoneRect[1] + 2 * ZONE_PAD_PTS}
            fill="var(--accent)"
            fillOpacity={0.07}
            stroke="var(--accent)"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
            rx={3}
          />
        </svg>
      ) : null}
      {/* Occurrences de la recherche. En z 5, SOUS le cache du rappel libre
          (z 6) : une occurrence dans le passage à restituer reste cachée. La
          courante, plus soutenue et cernée, est celle que « 3 / 17 » désigne. */}
      {findHits.length ? (
        <svg
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          aria-hidden
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 5 }}
        >
          {findHits.map((rects, hi) =>
            rects.map((r, ri) => {
              const current = hi === findCurrent;
              return (
                <rect
                  key={`${hi}-${ri}`}
                  data-find=""
                  {...(current ? { "data-find-current": "" } : {})}
                  x={r[0] - 1}
                  y={r[1] - 1}
                  width={r[2] - r[0] + 2}
                  height={r[3] - r[1] + 2}
                  fill={current ? "var(--find-current)" : "var(--find-hit)"}
                  fillOpacity={current ? 0.42 : 0.32}
                  stroke={current ? "var(--find-current)" : "none"}
                  strokeWidth={1.5}
                  vectorEffect="non-scaling-stroke"
                  rx={1.5}
                />
              );
            }),
          )}
        </svg>
      ) : null}
      {/* Ancre de la visite guidée sur le passage cité (cf.
          `highlightBounds`). Invisible et inerte : elle ne sert
          qu'à donner un rectangle à éclairer au voile. */}
      {demo && highlights?.length ? (
        <div
          aria-hidden
          data-tour="quote"
          style={{ position: "absolute", ...highlightBounds(highlights, scale), pointerEvents: "none" }}
        />
      ) : null}
      {/* Rappel libre : cache opaque sur le passage à restituer. Il
          recouvre le calque de texte, donc on ne peut ni le lire ni
          le sélectionner tant que la réponse n'est pas donnée. */}
      {mask?.length ? (
        <svg
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          aria-label={t("qa.recall.masked")}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", zIndex: 6 }}
        >
          {mask.map((rect, ri) => (
            <rect
              key={ri}
              x={rect[0] - MASK_PAD_PTS}
              y={rect[1] - MASK_PAD_PTS}
              width={rect[2] - rect[0] + 2 * MASK_PAD_PTS}
              height={rect[3] - rect[1] + 2 * MASK_PAD_PTS}
              // Opaque, explicitement : la variable de thème est
              // pleine, mais rien ne doit pouvoir la rendre
              // translucide (transition d'opacité, thème tiers).
              fill="var(--surface-soft)"
              fillOpacity={1}
              stroke="var(--border-strong)"
              strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke"
              rx={3}
            />
          ))}
        </svg>
      ) : null}
      {/* Calque de texte transparent : sélection native par-dessus l'image. */}
      {words ? <PageTextLayer words={words} scale={scale} /> : null}
      {/* Surlignages mémorisés (cliquables pour suppression). */}
      {saved.length ? (
        <svg
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
        >
          {saved.map((hl) =>
            hl.rects.map((r, ri) => (
              <rect
                key={`${hl.id}-${ri}`}
                x={r[0]}
                y={r[1]}
                width={r[2] - r[0]}
                height={r[3] - r[1]}
                fill={hl.fill}
                opacity={0.32}
                rx={1}
                style={{ pointerEvents: "all", cursor: "pointer" }}
                onClick={() => onDeleteHighlight(hl.id)}
              />
            )),
          )}
        </svg>
      ) : null}
      {onToggleBookmark ? <PageBookmarkButton page={page} active={bookmarked} onToggle={onToggleBookmark} /> : null}
    </div>
  );
});
