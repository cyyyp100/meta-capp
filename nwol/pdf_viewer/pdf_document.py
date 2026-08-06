# pdf_viewer/pdf_document.py — Accès PDF léger (PyMuPDF) pour le lecteur page-par-page
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("pdf_viewer.document")


class PdfDocument:
    """Enveloppe fine autour de PyMuPDF (fitz).

    Volontairement minimale : pas de reconstruction de blocs, pas d'OCR. La
    page rendue en image est la source primaire pour le lecteur ; le texte brut
    n'est qu'un contexte secondaire transmis au LLM, et les tailles de police
    servent à la détection de titres quand le PDF n'a pas de sommaire natif.
    """

    def __init__(self, path: str):
        self.path = str(Path(path).resolve())
        self.filename = Path(path).name
        self._doc = None

    def open(self) -> "PdfDocument":
        import fitz

        self._doc = fitz.open(self.path)
        return self

    def close(self) -> None:
        if self._doc is not None:
            try:
                self._doc.close()
            finally:
                self._doc = None

    def __enter__(self) -> "PdfDocument":
        return self.open()

    def __exit__(self, *_exc) -> None:
        self.close()

    def _require_open(self):
        if self._doc is None:
            raise RuntimeError("PdfDocument non ouvert (appeler .open()).")
        return self._doc

    def page_count(self) -> int:
        return len(self._require_open())

    def toc(self) -> list[dict]:
        """Sommaire natif normalisé : [{level, title, page}] (page 1-based)."""
        raw = self._require_open().get_toc() or []
        entries: list[dict] = []
        for item in raw:
            try:
                level, title, page = int(item[0]), str(item[1]).strip(), int(item[2])
            except (TypeError, ValueError, IndexError):
                continue
            if title and page >= 1:
                entries.append({"level": max(1, level), "title": title, "page": page})
        return entries

    def page_sizes(self) -> list[tuple[float, float]]:
        """Dimensions (largeur, hauteur) en points de chaque page, ordre 1..N.

        Sert au lecteur scroll libre pour calculer la mise en page complète
        avant que les images soient rendues.
        """
        doc = self._require_open()
        sizes: list[tuple[float, float]] = []
        for page in doc:
            rect = page.rect
            sizes.append((float(rect.width) or 595.0, float(rect.height) or 842.0))
        return sizes

    def raw_text(self, page_number: int) -> str:
        """Texte brut d'une page (contexte secondaire pour le LLM)."""
        doc = self._require_open()
        if page_number < 1 or page_number > len(doc):
            return ""
        try:
            return doc[page_number - 1].get_text("text") or ""
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("raw_text page %s: %s", page_number, exc)
            return ""

    def search_text(self, page_number: int, needle: str) -> list[tuple[float, float, float, float]]:
        """Localise un texte sur une page → rects (x0, y0, x1, y1) en points PDF.

        Enveloppe fine de page.search_for (insensible à la casse, tolère les
        retours à la ligne). Liste vide si introuvable ou page invalide.
        """
        doc = self._require_open()
        if not needle or page_number < 1 or page_number > len(doc):
            return []
        try:
            rects = doc[page_number - 1].search_for(needle)
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("search_text page %s: %s", page_number, exc)
            return []
        return [(float(r.x0), float(r.y0), float(r.x1), float(r.y1)) for r in rects or []]

    def words(self, page_number: int) -> list[tuple[float, float, float, float, str]]:
        """Boîtes de mots d'une page → (x0, y0, x1, y1, mot) en points PDF.

        Alimente le calque de texte transparent du lecteur web (sélection native
        par-dessus l'image rendue). Liste vide si page invalide ou sans texte.
        """
        doc = self._require_open()
        if page_number < 1 or page_number > len(doc):
            return []
        try:
            raw = doc[page_number - 1].get_text("words")
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("words page %s: %s", page_number, exc)
            return []
        result: list[tuple[float, float, float, float, str]] = []
        for item in raw or []:
            try:
                x0, y0, x1, y1, word = item[0], item[1], item[2], item[3], item[4]
            except (IndexError, TypeError):
                continue
            text = str(word).strip()
            if not text:
                continue
            result.append((float(x0), float(y0), float(x1), float(y1), text))
        return result

    def line_sizes(self, page_number: int) -> list[tuple[str, float]]:
        """Renvoie [(texte_de_ligne, taille_police_max)] pour une page.

        Utilisé par la détection de titres par taille de police. La taille
        retenue par ligne est la plus grande taille de span de cette ligne.
        """
        doc = self._require_open()
        if page_number < 1 or page_number > len(doc):
            return []
        try:
            data = doc[page_number - 1].get_text("dict")
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("line_sizes page %s: %s", page_number, exc)
            return []

        lines: list[tuple[str, float]] = []
        for block in data.get("blocks", []):
            if block.get("type") != 0:  # 0 = bloc de texte
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(span.get("text", "") for span in spans).strip()
                if not text:
                    continue
                size = max((float(span.get("size", 0.0)) for span in spans), default=0.0)
                lines.append((text, size))
        return lines
