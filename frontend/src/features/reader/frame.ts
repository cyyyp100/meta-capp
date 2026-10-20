// features/reader/frame.ts — Amener un rectangle d'une page PDF au milieu de la vue.
//
// La géométrie seule, sans DOM : le lecteur mesure la page et la vue, ce module
// calcule le défilement. Elle vivait dans `lockFrame()` (le cadrage d'une
// question bloquante) ; la recherche (Ctrl/Cmd+F) cadre ses occurrences de la
// même façon, et deux copies d'un cadrage divergent. `frame.test.ts` fige le
// comportement de la question bloquante.

export interface PageGeometry {
  /** Haut de la page en coordonnées de défilement (px). */
  pageTop: number;
  /** Bord gauche de la page, relatif à la vue (px). */
  pageLeft: number;
  /** scrollTop maximal de la vue. */
  maxTop: number;
  /** Partie visible de la vue (px). */
  viewWidth: number;
  viewHeight: number;
  /** Pixels par point PDF au zoom courant. */
  scale: number;
}

export interface FrameOptions {
  /** Marge autour du rectangle, en points PDF. */
  pad: number;
  /** Ce qui recouvre la vue en haut (barre d'outils, bannière), en bas, sur les côtés (px). */
  topInset: number;
  bottomInset: number;
  sideInset: number;
  zoom: number;
  minZoom: number;
  maxZoom: number;
}

export interface Frame {
  /** scrollTop qui centre le rectangle dans la partie libre de la vue. */
  top: number;
  /** Décalage horizontal (px) qui le ramène dans la vue. */
  dx: number;
  /** Zoom sous lequel il tiendrait entier, s'il ne tient pas au zoom courant. */
  fitZoom: number | null;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/**
 * Cadrage d'un rectangle `[x0, y0, x1, y1]` (points PDF, origine haut-gauche)
 * de la page décrite par `geo` : centré verticalement dans la partie libre de
 * la vue, ramené dans la vue horizontalement, et le zoom qui le ferait tenir
 * s'il déborde. Sans rectangle, le haut de la page.
 */
export function frameRect(geo: PageGeometry, rect: number[] | null, opts: FrameOptions): Frame {
  const { pageTop, pageLeft, maxTop, viewWidth, viewHeight, scale } = geo;
  if (!rect) return { top: clamp(pageTop, 0, maxTop), dx: 0, fitZoom: null };
  const { pad, topInset, bottomInset, sideInset, zoom, minZoom, maxZoom } = opts;
  const [x0, y0, x1, y1] = rect;
  const zoneW = (x1 - x0 + 2 * pad) * scale;
  const zoneH = (y1 - y0 + 2 * pad) * scale;
  const availW = viewWidth - 2 * sideInset;
  const availH = viewHeight - topInset - bottomInset;
  let fitZoom: number | null = null;
  if ((zoneH > availH || zoneW > availW) && zoom > minZoom) {
    const z = clamp(Math.min(availH / zoneH, availW / zoneW) * zoom * 0.96, minZoom, maxZoom);
    if (z < zoom - 0.01) fitZoom = z;
  }
  const zoneTop = pageTop + (y0 - pad) * scale;
  const top = zoneTop - topInset - Math.max(0, (availH - zoneH) / 2);
  const zoneLeft = pageLeft + (x0 - pad) * scale;
  const zoneRight = zoneLeft + zoneW;
  let dx = 0;
  if (zoneLeft < sideInset) dx = sideInset - zoneLeft;
  else if (zoneRight > viewWidth - sideInset) dx = viewWidth - sideInset - zoneRight;
  return { top: clamp(top, 0, maxTop), dx, fitZoom };
}

/** Boîte englobante [x0, y0, x1, y1] d'une liste de rects (points PDF). */
export function boundsOf(rects: number[][]): number[] {
  return [
    Math.min(...rects.map((r) => r[0])),
    Math.min(...rects.map((r) => r[1])),
    Math.max(...rects.map((r) => r[2])),
    Math.max(...rects.map((r) => r[3])),
  ];
}
