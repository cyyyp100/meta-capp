# reader/highlights.py — Localisation des citations LLM dans la page PDF
#
# Le LLM renvoie des citations censées être verbatim ; ce module les retrouve
# dans la page avec une tolérance croissante : texte exact → normalisé →
# segments de phrase. Échec silencieux : une citation hallucinée ne produit
# simplement aucun surlignage. La conversion points PDF → pixels canvas vit
# ici aussi pour rester testable sans Tk.
from __future__ import annotations

import re
from typing import Callable

Rect = tuple[float, float, float, float]

MIN_QUOTE_CHARS = 15
_SEGMENT_MIN_CHARS = 20
_SEGMENT_HEAD_CHARS = 60
_MAX_RECTS_PER_QUOTE = 12

_LIGATURES = str.maketrans({
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "’": "'", "‘": "'", "“": '"', "”": '"', "«": '"', "»": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
})
_WS_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"[.;:!?]\s+")


def normalize_quote(text: str) -> str:
    """Rapproche la citation du texte extrait du PDF (espaces, ligatures, guillemets)."""
    return _WS_RE.sub(" ", (text or "").translate(_LIGATURES)).strip()


def _segments(quote: str) -> list[str]:
    """Segments de repli quand la citation entière est introuvable."""
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(quote)]
    segments = [p for p in parts if len(p) >= _SEGMENT_MIN_CHARS]
    if segments:
        return segments
    head = quote[:_SEGMENT_HEAD_CHARS].strip()
    return [head] if len(head) >= _SEGMENT_MIN_CHARS else []


def find_quote_rects(search: Callable[[str], list[Rect]], quote: str) -> list[Rect]:
    """Localise une citation via une fonction de recherche page → rects PDF.

    `search` est typiquement `lambda s: doc.search_text(page, s)`. Trois essais :
    citation brute, citation normalisée, puis segments de phrase fusionnés.
    """
    raw = (quote or "").strip()
    if len(raw) < MIN_QUOTE_CHARS:
        return []
    rects = search(raw)
    if rects:
        return rects[:_MAX_RECTS_PER_QUOTE]

    norm = normalize_quote(raw)
    if norm and norm != raw:
        rects = search(norm)
        if rects:
            return rects[:_MAX_RECTS_PER_QUOTE]

    merged: list[Rect] = []
    for segment in _segments(norm or raw):
        merged.extend(search(segment))
        if len(merged) >= _MAX_RECTS_PER_QUOTE:
            break
    return merged[:_MAX_RECTS_PER_QUOTE]


def rects_to_canvas(rects: list[Rect], scale: float, offset_x: float, offset_y: float) -> list[Rect]:
    """Convertit des rects en points PDF vers les coordonnées canvas du lecteur.

    `scale` = largeur_affichée_px / largeur_page_points (l'aspect est conservé,
    le même facteur s'applique donc aux deux axes).
    """
    return [
        (
            offset_x + x0 * scale,
            offset_y + y0 * scale,
            offset_x + x1 * scale,
            offset_y + y1 * scale,
        )
        for x0, y0, x1, y1 in rects
    ]
