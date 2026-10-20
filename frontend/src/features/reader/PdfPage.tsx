import { memo, useEffect, useMemo, useRef, useState } from "react";

import { MathText } from "../../components/MathText";
import { pageImageUrl } from "../../api/client";
import type { AnnotationLabel, AnnotationStyle, PageWord, ReaderNote } from "../../api/types";
import { useT } from "../../i18n";
import { PageNotesLayer } from "./annotations/PageNotesLayer";
import { svgStyle } from "./annotations/palette";
import { PageBookmarkButton } from "./PageBookmarkButton";
import { PageTextLayer } from "./PageTextLayer";

/** Marge (en points PDF) autour du passage cité, pour le liseré de la zone. */
export const ZONE_PAD_PTS = 4;
// Marge du cache de rappel libre : couvre jambages et interlignes, sinon les
// hampes des lignes voisines laissent deviner le passage.
const MASK_PAD_PTS = 2.5;

/** Surlignage mémorisé d'une page, prêt à dessiner (rects fusionnés par ligne,
 *  couleur et nom de l'étiquette résolus). */
export interface SavedPageHighlight {
  id: number;
  fill: string;
  style: AnnotationStyle;
  rects: number[][];
  note: string | null;
  labelName: string;
}

/** Aucune note sur la page : la même liste à chaque rendu (la page est mémoïsée). */
export const NO_NOTES: ReaderNote[] = [];
const NO_LABELS = new Map<number, AnnotationLabel>();
// Ce qui, sur la page, a son propre clic : un clic dessus n'édite pas le
// surlignage qu'il recouvre.
const OWN_CLICK = "button, a, input, textarea, select, [data-note]";

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
  /** Clic sur un surlignage mémorisé : son édition (étiquette, style, note). */
  onEditHighlight: (id: number) => void;
  /** Post-it et signets de la page (`NO_NOTES` sans). */
  notes?: ReaderNote[];
  labelsById?: Map<number, AnnotationLabel>;
  /** Absent : post-it et signets en lecture seule (visite guidée). */
  onEditNote?: (id: number) => void;
  /** Élément que le carnet vient de désigner (« h-12 », « n-3 ») : il clignote. */
  flash?: string | null;
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
  onEditHighlight,
  notes = NO_NOTES,
  labelsById = NO_LABELS,
  onEditNote,
  flash = null,
  onToggleBookmark,
}: Props) {
  const t = useT();
  const scale = width / w;
  // Note d'un surlignage dont on survole la pastille : une petite carte la montre.
  const [peek, setPeek] = useState<number | null>(null);
  const peeked = peek !== null ? saved.find((hl) => hl.id === peek && hl.note) : undefined;
  // Les surlignages enregistrés ne captent plus le pointeur : leurs rects
  // couvraient le texte, et on ne pouvait ni commencer ni prolonger une
  // sélection par-dessus — elle sautait au bout de la page. La page reconnaît
  // elle-même, par la géométrie, le surlignage sous un clic ou un survol.
  const [hovered, setHovered] = useState<number | null>(null);
  const hoveredHl = hovered !== null ? saved.find((hl) => hl.id === hovered) : undefined;
  function highlightAt(e: React.MouseEvent<HTMLDivElement>): SavedPageHighlight | undefined {
    if (!saved.length) return undefined;
    const box = e.currentTarget.getBoundingClientRect();
    const k = box.width / w; // l'échelle affichée, geste de zoom en cours compris
    const x = (e.clientX - box.left) / k;
    const y = (e.clientY - box.top) / k;
    // Le dernier dessiné est au-dessus.
    for (let i = saved.length - 1; i >= 0; i--) {
      if (saved[i].rects.some((r) => x >= r[0] && x <= r[2] && y >= r[1] && y <= r[3])) return saved[i];
    }
    return undefined;
  }
  // Le cache d'un rappel libre retire ses mots du calque de texte : le passage
  // ne se sélectionne ni ne se copie dessous. Le reste de la page, si.
  const hidden = useMemo(
    () => mask?.map((r) => [r[0] - MASK_PAD_PTS, r[1] - MASK_PAD_PTS, r[2] + MASK_PAD_PTS, r[3] + MASK_PAD_PTS]),
    [mask],
  );
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
      {...(hoveredHl ? { "data-hl-hover": "" } : {})}
      title={hoveredHl ? (hoveredHl.note ? `${hoveredHl.labelName} — ${hoveredHl.note}` : hoveredHl.labelName) : undefined}
      onClick={(e) => {
        // Un clic posé sur un surlignage l'édite ; la fin d'un glissé de
        // sélection, non (la sélection n'est alors pas vide).
        if (!saved.length || (e.target as Element).closest(OWN_CLICK)) return;
        if (!document.getSelection()?.isCollapsed) return;
        const hl = highlightAt(e);
        if (hl) onEditHighlight(hl.id);
      }}
      onMouseMove={
        saved.length
          ? (e) => {
              // Pendant un glissé, le curseur reste celui de la sélection.
              if (e.buttons) return;
              const id = highlightAt(e)?.id ?? null;
              if (id !== hovered) setHovered(id);
            }
          : undefined
      }
      onMouseLeave={() => setHovered(null)}
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
      {/* Rappel libre : cache opaque sur le passage à restituer. On ne
          peut ni le lire ni le sélectionner tant que la réponse n'est pas
          donnée — ses mots sont retirés du calque de texte (`hidden`) ; le
          cache, lui, laisse passer le pointeur vers le reste de la page. */}
      {mask?.length ? (
        <svg
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          aria-label={t("qa.recall.masked")}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", zIndex: 6, pointerEvents: "none" }}
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
      {words ? <PageTextLayer words={words} scale={scale} hidden={hidden} /> : null}
      {/* Surlignages mémorisés : tracés selon leur style (surligné, souligné,
          barré, encadré), à la couleur de leur étiquette. Un clic sur la ligne
          l'édite (cf. `highlightAt`) ; ses rects pleins (`data-hl`) servent
          d'ancre à la popover et au clignotement, sans capter le pointeur. */}
      {saved.length ? (
        <svg
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
        >
          {saved.map((hl) => (
            <g key={hl.id} {...(flash === `h-${hl.id}` ? { "data-flash": "" } : {})}>
              {hl.rects.map((r, ri) => {
                const mark = svgStyle(hl.style, hl.fill, r);
                return (
                  <rect
                    key={ri}
                    x={mark.x}
                    y={mark.y}
                    width={mark.width}
                    height={mark.height}
                    fill={mark.fill}
                    fillOpacity={mark.fillOpacity}
                    stroke={mark.stroke}
                    strokeWidth={mark.stroke ? 1.5 : undefined}
                    vectorEffect={mark.stroke ? "non-scaling-stroke" : undefined}
                    rx={1}
                  />
                );
              })}
              {hl.rects.map((r, ri) => (
                <rect
                  key={`hit-${ri}`}
                  data-hl={hl.id}
                  x={r[0]}
                  y={r[1]}
                  width={r[2] - r[0]}
                  height={r[3] - r[1]}
                  fill="transparent"
                />
              ))}
            </g>
          ))}
        </svg>
      ) : null}
      {/* Pastille d'un surlignage annoté, au bout de sa première ligne : au
          survol, la note (formules rendues) ; au clic, l'édition. */}
      {saved.map((hl) => {
        if (!hl.note || !hl.rects.length) return null;
        const r = hl.rects[0];
        return (
          <button
            key={`note-${hl.id}`}
            type="button"
            data-hl={hl.id}
            aria-label={t("annotations.note_of", { label: hl.labelName })}
            onClick={() => onEditHighlight(hl.id)}
            onMouseEnter={() => setPeek(hl.id)}
            onMouseLeave={() => setPeek((p) => (p === hl.id ? null : p))}
            onFocus={() => setPeek(hl.id)}
            onBlur={() => setPeek((p) => (p === hl.id ? null : p))}
            style={{
              position: "absolute",
              left: r[2] * scale - 4,
              top: r[1] * scale - 6,
              width: 10,
              height: 10,
              padding: 0,
              borderRadius: 999,
              border: "1.5px solid #fff",
              background: hl.fill,
              boxShadow: "var(--shadow-sm)",
              cursor: "pointer",
              zIndex: 7,
            }}
          />
        );
      })}
      {peeked && peeked.note ? (
        <div
          role="tooltip"
          style={{
            position: "absolute",
            left: Math.min(peeked.rects[0][2] * scale + 8, width - 268),
            top: peeked.rects[0][1] * scale + 8,
            width: 260,
            maxHeight: 220,
            overflow: "hidden",
            padding: "8px 10px",
            background: "var(--surface)",
            color: "var(--text)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            boxShadow: "var(--shadow-md)",
            fontSize: 12.5,
            lineHeight: 1.45,
            whiteSpace: "pre-wrap",
            pointerEvents: "none",
            zIndex: 9,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4, color: "var(--text-soft)" }}>{peeked.labelName}</div>
          <MathText text={peeked.note} />
        </div>
      ) : null}
      <PageNotesLayer
        notes={notes}
        labelsById={labelsById}
        scale={scale}
        flashId={flash?.startsWith("n-") ? Number(flash.slice(2)) : null}
        onEdit={onEditNote}
      />
      {onToggleBookmark ? <PageBookmarkButton page={page} active={bookmarked} onToggle={onToggleBookmark} /> : null}
    </div>
  );
});
