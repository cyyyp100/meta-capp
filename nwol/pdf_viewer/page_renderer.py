# pdf_viewer/page_renderer.py — Rendu d'une page PDF en PNG haute résolution (cache disque)
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from config.settings import ASSETS_DIR

logger = logging.getLogger("pdf_viewer.renderer")

_CACHE_SUBDIR = "page_cache"

# Zoom de la vignette (page 1) affichée sur la page Bibliothèque du front.
# Doit rester aligné avec le front (Home.tsx : pageImageUrl(id, 1, 0.5)).
THUMBNAIL_ZOOM = 0.5


def _thumbnail_name() -> str:
    return f"page_{1:03d}_z{THUMBNAIL_ZOOM:g}.png"


def _pdf_hash(pdf_path: str) -> str:
    resolved = str(Path(pdf_path).resolve())
    return hashlib.sha1(resolved.encode("utf-8", errors="ignore")).hexdigest()[:8]


def page_cache_dir(pdf_path: str) -> Path:
    return Path(ASSETS_DIR) / _CACHE_SUBDIR / _pdf_hash(pdf_path)


def render_page(pdf_path: str, page_number: int, zoom: float = 2.5) -> str:
    """Rend la page (1-based) en PNG et renvoie le chemin du fichier.

    Réutilise le cache disque si le PNG existe déjà
    (``assets/page_cache/<pdf_hash>/page_NNN_z<zoom>.png``).
    """
    cache_dir = page_cache_dir(pdf_path)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"page_{page_number:03d}_z{zoom:g}.png"
    if out_path.exists():
        return str(out_path)

    import fitz

    with fitz.open(pdf_path) as doc:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(f"Page {page_number} hors limites (1..{len(doc)})")
        page = doc[page_number - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pix.save(str(out_path))
    logger.debug("Page rendue : %s", out_path)
    return str(out_path)


def clear_page_cache(pdf_path: str) -> None:
    """Supprime le cache PNG d'un PDF (appelé à la fermeture / réimport)."""
    cache_dir = page_cache_dir(pdf_path)
    if not cache_dir.exists():
        return
    for png in cache_dir.glob("page_*.png"):
        try:
            png.unlink()
        except OSError:
            pass


def clear_reader_cache(pdf_path: str) -> None:
    """Purge les pages rendues d'un PDF SAUF la vignette (page 1, zoom bibliothèque).

    Appelé à la fin d'une session de lecture : on ne conserve durablement que la
    vignette de la bibliothèque ; les pages lues (HD, multi-zoom) sont jetées
    pour borner le stockage disque.
    """
    cache_dir = page_cache_dir(pdf_path)
    if not cache_dir.exists():
        return
    keep = _thumbnail_name()
    for png in cache_dir.glob("page_*.png"):
        if png.name == keep:
            continue
        try:
            png.unlink()
        except OSError:
            pass
