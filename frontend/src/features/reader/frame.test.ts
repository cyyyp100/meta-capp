// frame.test.ts — Le cadrage de la question bloquante, extrait de `lockFrame()`.
//
// La recherche (Ctrl/Cmd+F) s'en sert aussi : ces cas figent le comportement
// d'avant l'extraction, valeurs calculées à la main sur sa formule.
import { describe, expect, it } from "vitest";

import { boundsOf, frameRect, type PageGeometry } from "./frame";

const geo: PageGeometry = { pageTop: 1500, pageLeft: 100, maxTop: 5000, viewWidth: 1000, viewHeight: 800, scale: 1.4 };
// Les valeurs du lecteur : ZONE_PAD_PTS, ZONE_TOP/BOTTOM/SIDE_INSET, MIN/MAX_ZOOM.
const opts = { pad: 4, topInset: 112, bottomInset: 24, sideInset: 24, zoom: 1, minZoom: 0.5, maxZoom: 4 };

describe("frameRect", () => {
  it("sans rectangle, cadre le haut de la page, borné au défilement possible", () => {
    expect(frameRect(geo, null, opts)).toEqual({ top: 1500, dx: 0, fitZoom: null });
    expect(frameRect({ ...geo, pageTop: 6000 }, null, opts)).toEqual({ top: 5000, dx: 0, fitZoom: null });
  });

  it("centre le rectangle dans la partie libre de la vue", () => {
    // Zone : 330,4 × 95,2 px, dans 952 × 664 px libres.
    const frame = frameRect(geo, [72, 100, 300, 160], opts);
    expect(frame.top).toBeCloseTo(1238, 6);
    expect(frame.dx).toBe(0);
    expect(frame.fitZoom).toBeNull();
  });

  it("ramène dans la vue un rectangle sorti à gauche ou à droite", () => {
    expect(frameRect({ ...geo, pageLeft: -200 }, [72, 100, 300, 160], opts).dx).toBeCloseTo(128.8, 6);
    expect(frameRect({ ...geo, pageLeft: 800 }, [72, 100, 300, 160], opts).dx).toBeCloseTo(-249.6, 6);
  });

  it("propose le zoom sous lequel un rectangle trop haut tiendrait, jamais sous le minimum", () => {
    const frame = frameRect(geo, [72, 100, 300, 700], opts);
    expect(frame.fitZoom).toBeCloseTo((664 / 851.2) * 0.96, 6);
    // Trop haut pour être centré : son haut sous la barre d'outils.
    expect(frame.top).toBeCloseTo(1522.4, 6);
    expect(frameRect(geo, [72, 100, 300, 700], { ...opts, zoom: 0.5 }).fitZoom).toBeNull();
  });

  it("ne remonte jamais au-dessus du début du document", () => {
    expect(frameRect({ ...geo, pageTop: 0 }, [0, 0, 100, 20], opts).top).toBe(0);
  });
});

describe("boundsOf", () => {
  it("englobe les rects d'une occurrence sur deux lignes", () => {
    expect(boundsOf([[150, 63, 193, 72], [72, 80, 102, 89]])).toEqual([72, 63, 193, 89]);
  });
});
