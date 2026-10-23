"""Construit les SVG Clikoda (piste 5, Maman cachalot) en tracés aplatis.

    pip install skia-pathops   # hors requirements : outil de dessin seulement
    python build-clikoda.py <dossier de sortie>

Les PNG 1024 se réexportent ensuite depuis les SVG, puis
`scripts/build_icons.py` refait les icônes de l'application.

Toutes les formes finales sont des chemins pleins : pas de masque, pas de
stroke, pas de style, pas d'id. Les trous (œil, sourire) sont de vrais trous.
"""
import sys
from pathlib import Path as P
import pathops
from pathops import Path, PathOp, LineCap, LineJoin

OUT = P(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

TEAL = "#135863"
MIST = "#EEF4F1"
AMBER = "#E0A458"
K = 0.5522847498


def circle(cx, cy, r):
    p = Path()
    k = K * r
    p.moveTo(cx + r, cy)
    p.cubicTo(cx + r, cy + k, cx + k, cy + r, cx, cy + r)
    p.cubicTo(cx - k, cy + r, cx - r, cy + k, cx - r, cy)
    p.cubicTo(cx - r, cy - k, cx - k, cy - r, cx, cy - r)
    p.cubicTo(cx + k, cy - r, cx + r, cy - k, cx + r, cy)
    p.close()
    return p


def body():
    p = Path()
    p.moveTo(22, 44)
    p.cubicTo(46, 30, 88, 24, 140, 24)
    p.cubicTo(168, 24, 182, 36, 182, 60)
    p.lineTo(182, 78)
    p.cubicTo(182, 92, 174, 98, 160, 98)
    p.lineTo(74, 98)
    p.cubicTo(54, 98, 36, 104, 24, 114)
    p.cubicTo(34, 92, 34, 66, 22, 44)
    p.close()
    return p


def jaw():
    p = Path()
    p.moveTo(74, 105)
    p.lineTo(154, 105)
    p.cubicTo(161, 105, 161, 112, 154, 112)
    p.lineTo(88, 114)
    p.cubicTo(78, 114, 72, 111, 74, 105)
    p.close()
    return p


def smile():
    p = Path()
    p.moveTo(80, 102)
    p.cubicTo(72, 102, 66, 98, 64, 92)
    p.stroke(5, LineCap.ROUND_CAP, LineJoin.ROUND_JOIN, 4)
    p.convertConicsToQuads()
    return p


def union(*paths):
    r = Path()
    for q in paths:
        r = pathops.op(r, q, PathOp.UNION)
    return r


def diff(a, b):
    return pathops.op(a, b, PathOp.DIFFERENCE)


def whale():
    w = union(body(), jaw())
    w = diff(w, union(circle(84, 78, 5), smile()))
    return w


def clicks(xs=(174, 190, 206, 226, 242), r=5):
    return union(*[circle(x, 108, r) for x in xs])


def rect(x, y, w, h):
    p = Path()
    p.moveTo(x, y)
    p.lineTo(x + w, y)
    p.lineTo(x + w, y + h)
    p.lineTo(x, y + h)
    p.close()
    return p


def whale_small():
    """Silhouette pleine pour 16-32 px : mâchoire soudée, œil agrandi, pas de sourire."""
    w = union(body(), jaw(), rect(76, 96, 78, 11))
    return diff(w, circle(92, 70, 8.5))


def transform(p, s, tx, ty):
    q = Path()
    for verb, pts in p.segments:
        pts = [(x * s + tx, y * s + ty) for x, y in pts]
        if verb == "moveTo":
            q.moveTo(*pts[0])
        elif verb == "lineTo":
            q.lineTo(*pts[0])
        elif verb == "curveTo":
            q.cubicTo(*pts[0], *pts[1], *pts[2])
        elif verb == "qCurveTo":
            # suite de quadratiques TrueType : points implicites au milieu
            cur = pts
            for i in range(len(cur) - 1):
                c = cur[i]
                end = cur[i + 1] if i == len(cur) - 2 else ((cur[i][0] + cur[i + 1][0]) / 2, (cur[i][1] + cur[i + 1][1]) / 2)
                q.quadTo(*c, *end)
        elif verb == "closePath":
            q.close()
    return q


def d(p, nd=2):
    def fmt(v):
        return f"{round(v, nd):g}"

    def pt(a):
        return f"{fmt(a[0])} {fmt(a[1])}"

    out = []
    for verb, pts in p.segments:
        if verb == "qCurveTo":
            # suite TrueType : un point « on-curve » implicite entre deux contrôles
            for i in range(len(pts) - 1):
                end = pts[i + 1] if i == len(pts) - 2 else (
                    (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2)
                out.append(f"Q{pt(pts[i])} {pt(end)}")
            continue
        flat = " ".join(pt(a) for a in pts)
        out.append({"moveTo": "M", "lineTo": "L", "curveTo": "C",
                    "closePath": "Z", "endPath": ""}[verb] + flat)
    return "".join(out)


def bbox(p):
    return p.bounds  # (xmin, ymin, xmax, ymax)


def rounded_square(x, y, size, r):
    p = Path()
    k = K * r
    p.moveTo(x + r, y)
    p.lineTo(x + size - r, y)
    p.cubicTo(x + size - r + k, y, x + size, y + r - k, x + size, y + r)
    p.lineTo(x + size, y + size - r)
    p.cubicTo(x + size, y + size - r + k, x + size - r + k, y + size, x + size - r, y + size)
    p.lineTo(x + r, y + size)
    p.cubicTo(x + r - k, y + size, x, y + size - r + k, x, y + size - r)
    p.lineTo(x, y + r)
    p.cubicTo(x, y + r - k, x + r - k, y, x + r, y)
    p.close()
    return p


def svg(view, body_xml, label):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" '
            f'role="img" aria-label="{label}">\n{body_xml}\n</svg>\n')


# ---------- 1. Tête seule : le cachalot sans les clics, cadrage serré ----------
w = whale()
x0, y0, x1, y1 = bbox(w)
pad = 2
W, H = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
head = transform(w, 1, -x0 + pad, -y0 + pad)
(OUT / "clikoda-tete.svg").write_text(svg(
    f"0 0 {W:g} {H:g}",
    f'<path fill="currentColor" d="{d(head)}"/>',
    "Clikoda"))

# ---------- 2. Symbole : cachalot + coda, fond transparent (favicon, en-tête) ----------
c = clicks()
allb = union(w, c)
x0, y0, x1, y1 = bbox(allb)
S = 512
inner = S * 0.88
s = inner / max(x1 - x0, y1 - y0)
tx = (S - (x1 - x0) * s) / 2 - x0 * s
ty = (S - (y1 - y0) * s) / 2 - y0 * s
(OUT / "clikoda-symbole.svg").write_text(svg(
    f"0 0 {S} {S}",
    f'<path fill="{TEAL}" d="{d(transform(w, s, tx, ty))}"/>\n'
    f'<path fill="{AMBER}" d="{d(transform(c, s, tx, ty))}"/>',
    "Clikoda"))

# ---------- 3. Icône d'app : squircle 824 dans 1024 (grille macOS) ----------
S = 1024
tile_x, tile = 100, 824
radius = 185
tile_path = rounded_square(tile_x, tile_x, tile, radius)


def icon(art_parts, width_ratio, name, dy=0.0):
    allp = union(*[p for p, _ in art_parts])
    x0, y0, x1, y1 = bbox(allp)
    s = tile * width_ratio / (x1 - x0)
    tx = (S - (x1 - x0) * s) / 2 - x0 * s
    ty = (S - (y1 - y0) * s) / 2 - y0 * s + tile * dy
    layers = [f'<path fill="{TEAL}" d="{d(tile_path)}"/>']
    layers += [f'<path fill="{col}" d="{d(transform(p, s, tx, ty))}"/>' for p, col in art_parts]
    (OUT / name).write_text(svg(f"0 0 {S} {S}", "\n".join(layers), "Clikoda"))


tight = clicks(xs=(171, 185, 199, 218, 232), r=5)
icon([(w, MIST)], 0.80, "clikoda-icone.svg", dy=0.0)
# petites tailles (16-32 px, favicon) : cachalot seul, plus gros
icon([(whale_small(), MIST)], 0.80, "clikoda-icone-petit.svg", dy=0.0)

print("ok")
