"""Construit les icônes de l'application à partir des sources de `desktop/icons/source/`.

    python scripts/build_icons.py

Les sources sont les deux rendus 1024 px du logo (Clikoda, le cachalot) :
`clikoda-icone-1024.png` pour les grandes tailles et `clikoda-icone-petit-1024.png`,
la silhouette simplifiée (œil agrandi, mâchoire soudée), pour 16 à 32 pt — à ces
tailles le sourire et l'œil fin du dessin complet ne font plus qu'un pixel gris.
Les SVG et leur générateur (`build-clikoda.py`) restent à côté : c'est là qu'on
retouche le dessin, puis on réexporte les deux PNG et on relance ce script.

Produit, et versionne :
  desktop/icons/meta-capp.icns   bundle macOS (desktop/metacapp.spec)
  desktop/icons/meta-capp.ico    exécutable Windows (idem)
  frontend/public/favicon.ico    onglet du navigateur (mode navigateur, Linux)
  frontend/public/favicon.svg    idem, vectoriel ; aussi la marque de la barre latérale

La grille macOS laisse 100 px de marge autour de la tuile de 824 px : c'est le
rendu attendu dans le Dock, pas ailleurs. Windows et les onglets recadrent sur
la tuile, sinon l'icône y paraît d'un cinquième trop petite.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "desktop" / "icons" / "source"
FULL = SOURCE / "clikoda-icone-1024.png"
SMALL = SOURCE / "clikoda-icone-petit-1024.png"
SMALL_SVG = SOURCE / "clikoda-icone-petit.svg"

# Tuile du logo dans le carré de 1024 (build-clikoda.py : tile_x, tile).
TILE = (100, 100, 924, 924)
# En deçà, la silhouette simplifiée (tailles en points : 32 pt @2x reste petit).
SMALL_MAX = 32


def _resized(image: Image.Image, size: int) -> Image.Image:
    return image.resize((size, size), Image.LANCZOS, reducing_gap=3.0)


def _source(points: int, *, cropped: bool) -> Image.Image:
    image = Image.open(SMALL if points <= SMALL_MAX else FULL).convert("RGBA")
    return image.crop(TILE) if cropped else image


def build_icns(out: Path) -> None:
    """`iconutil` (macOS) : le seul à écrire toutes les entrées, 1x comprises."""
    if not shutil.which("iconutil"):
        print("iconutil introuvable (macOS uniquement) : meta-capp.icns non régénéré", file=sys.stderr)
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "meta-capp.iconset"
        iconset.mkdir()
        for points in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                suffix = "" if scale == 1 else "@2x"
                image = _resized(_source(points, cropped=False), points * scale)
                image.save(iconset / f"icon_{points}x{points}{suffix}.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)


def build_ico(out: Path, sizes: tuple[int, ...]) -> None:
    images = [_resized(_source(size, cropped=True), size) for size in sizes]
    largest = images[-1]
    largest.save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])


def build_favicon_svg(out: Path) -> None:
    """La silhouette simplifiée, recadrée sur sa tuile (même raison que l'ICO)."""
    svg = SMALL_SVG.read_text(encoding="utf-8")
    svg, count = re.subn(r'viewBox="0 0 1024 1024"', 'viewBox="100 100 824 824"', svg)
    if count != 1:
        raise SystemExit(f"{SMALL_SVG.name} : viewBox 0 0 1024 1024 attendu")
    out.write_text(svg, encoding="utf-8")


def main() -> None:
    icons = ROOT / "desktop" / "icons"
    public = ROOT / "frontend" / "public"
    build_icns(icons / "meta-capp.icns")
    build_ico(icons / "meta-capp.ico", (16, 20, 24, 32, 40, 48, 64, 128, 256))
    build_ico(public / "favicon.ico", (16, 32, 48))
    build_favicon_svg(public / "favicon.svg")
    print("ok")


if __name__ == "__main__":
    main()
