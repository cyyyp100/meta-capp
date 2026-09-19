# pdf_viewer/pdf_document.py — Accès PDF léger (pypdfium2) pour le lecteur page-par-page
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

from pdf_viewer.engine import PDFIUM_LOCK

logger = logging.getLogger("pdf_viewer.document")


class PdfDocument:
    """Enveloppe fine autour de pypdfium2 (moteur PDFium).

    Volontairement minimale : pas de reconstruction de blocs, pas d'OCR. La
    page rendue en image est la source primaire pour le lecteur ; le texte brut
    n'est qu'un contexte secondaire transmis au LLM, et les tailles de police
    servent à la détection de titres quand le PDF n'a pas de sommaire natif.

    PDFium et non PyMuPDF pour une raison de licence : Apache-2.0 / BSD-3-Clause
    contre AGPL-3.0 (voir architecture/07-pdf-et-code-reader.md).

    **Convention de coordonnées** : toutes les boîtes sorties d'ici sont en
    points PDF, origine EN HAUT À GAUCHE, y croissant vers le bas — la
    convention du SVG du lecteur et des surlignages déjà persistés en base.
    PDFium travaille en origine bas-gauche : l'inversion se fait ici, une seule
    fois, et jamais en aval.
    """

    def __init__(self, path: str):
        self.path = str(Path(path).resolve())
        self.filename = Path(path).name
        self._doc = None

    def open(self) -> "PdfDocument":
        """Ouvre le document ET prend le verrou moteur jusqu'à `close()`.

        Le verrou couvre toute la durée de vie du document : les handles de
        page et de texte que rendent les méthodes ci-dessous ne survivent pas à
        l'entrée d'un autre thread dans PDFium (voir `pdf_viewer/engine.py`).
        Tout usage passe donc par `with PdfDocument(...)` ou un `try/finally`.
        """
        import pypdfium2 as pdfium

        if self._doc is not None:
            # Déjà ouvert : ne PAS reprendre le verrou, un seul `close()`
            # suivra et il ne libérerait qu'une des deux prises (RLock).
            return self
        PDFIUM_LOCK.acquire()
        try:
            self._doc = pdfium.PdfDocument(self.path)
        except BaseException:
            # Rien n'est ouvert : on ne garde pas le verrou pour autant.
            PDFIUM_LOCK.release()
            raise
        return self

    def close(self) -> None:
        if self._doc is not None:
            try:
                self._doc.close()
            finally:
                self._doc = None
                PDFIUM_LOCK.release()

    def __enter__(self) -> "PdfDocument":
        return self.open()

    def __exit__(self, *_exc) -> None:
        self.close()

    def _require_open(self):
        if self._doc is None:
            raise RuntimeError("PdfDocument non ouvert (appeler .open()).")
        return self._doc

    @contextmanager
    def _page(self, page_number: int):
        """Ouvre une page 1-based et la referme. Cède ``None`` hors limites.

        PDFium garde un handle par page : on la referme systématiquement pour
        que l'indexation d'un document de plusieurs centaines de pages
        (``page_sizes``, ``chapter_index``) ne les accumule pas.
        """
        doc = self._require_open()
        if page_number < 1 or page_number > len(doc):
            yield None
            return
        page = doc[page_number - 1]
        try:
            yield page
        finally:
            page.close()

    def page_count(self) -> int:
        return len(self._require_open())

    def toc(self) -> list[dict]:
        """Sommaire natif normalisé : [{level, title, page}] (page 1-based)."""
        try:
            raw = list(self._require_open().get_toc())
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("toc %s: %s", self.filename, exc)
            return []
        entries: list[dict] = []
        for item in raw:
            try:
                # PDFium compte les niveaux et les pages à partir de 0.
                level = int(item.level) + 1
                title = str(item.title or "").strip()
                page = int(item.page_index) + 1
            except (TypeError, ValueError, AttributeError):
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
        for index in range(len(doc)):
            page = doc[index]
            try:
                width, height = page.get_size()
            finally:
                page.close()
            sizes.append((float(width) or 595.0, float(height) or 842.0))
        return sizes

    def raw_text(self, page_number: int) -> str:
        """Texte brut d'une page (contexte secondaire pour le LLM)."""
        try:
            with self._page(page_number) as page:
                if page is None:
                    return ""
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded() or ""
                finally:
                    textpage.close()
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("raw_text page %s: %s", page_number, exc)
            return ""
        # PDFium sépare les lignes par CRLF : on normalise en LF, comme le
        # reste de l'app (découpe en passages du RAG, prompts LLM). Un mot coupé
        # par un tiret en fin de ligne (« inter-\nmediate ») ressort avec un
        # U+0002 à la place du tiret : on le recolle, sinon ni la recherche
        # lexicale ni le LLM ne retrouvent « intermediate ».
        return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x02", "")

    def search_text(self, page_number: int, needle: str) -> list[tuple[float, float, float, float]]:
        """Localise un texte sur une page → rects (x0, y0, x1, y1) en points PDF.

        Insensible à la casse et tolérant aux retours à la ligne (PDFium
        recolle les lignes pendant la recherche). Une occurrence qui court sur
        plusieurs lignes donne un rect par ligne — le front les fusionne.
        Liste vide si introuvable ou page invalide.
        """
        if not needle:
            return []
        rects: list[tuple[float, float, float, float]] = []
        try:
            with self._page(page_number) as page:
                if page is None:
                    return []
                height = float(page.get_size()[1])
                textpage = page.get_textpage()
                try:
                    searcher = textpage.search(needle, match_case=False, match_whole_word=False)
                    try:
                        while True:
                            hit = searcher.get_next()
                            if hit is None:
                                break
                            index, count = hit
                            rects.extend(self._range_rects(textpage, index, count, height))
                    finally:
                        searcher.close()
                finally:
                    textpage.close()
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("search_text page %s: %s", page_number, exc)
            return []
        return rects

    def words(self, page_number: int) -> list[tuple[float, float, float, float, str]]:
        """Boîtes de mots d'une page → (x0, y0, x1, y1, mot) en points PDF.

        Alimente le calque de texte transparent du lecteur web (sélection native
        par-dessus l'image rendue). Liste vide si page invalide ou sans texte.

        PDFium n'expose que des caractères : on regroupe les suites non-blanches
        et on unit leurs boîtes. L'ordre reste celui du flux de contenu, comme
        le faisait ``get_text("words")``.
        """
        try:
            with self._page(page_number) as page:
                if page is None:
                    return []
                height = float(page.get_size()[1])
                textpage = page.get_textpage()
                try:
                    text = self._indexed_text(textpage)
                    return self._group_words(textpage, text, height)
                finally:
                    textpage.close()
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("words page %s: %s", page_number, exc)
            return []

    def line_sizes(self, page_number: int) -> list[tuple[str, float]]:
        """Renvoie [(texte_de_ligne, taille_police_max)] pour une page.

        Utilisé par la détection de titres par taille de police. La taille
        retenue par ligne est la plus grande taille de caractère de cette ligne.
        """
        try:
            with self._page(page_number) as page:
                if page is None:
                    return []
                textpage = page.get_textpage()
                try:
                    text = self._indexed_text(textpage)
                    return self._group_lines(textpage, text)
                finally:
                    textpage.close()
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("line_sizes page %s: %s", page_number, exc)
            return []

    # --- Accès bas niveau à la page de texte -------------------------------
    #
    # `_indexed_text` renvoie une chaîne dont l'index de chaque caractère est
    # AUSSI son index PDFium : c'est ce qui permet de remonter d'un caractère
    # du texte à sa boîte (`get_charbox`) ou à sa taille de police. Ne jamais
    # remplacer par `get_text_bounded()`, qui ne garantit pas cet alignement.

    @staticmethod
    def _indexed_text(textpage) -> str:
        count = textpage.count_chars()
        if count <= 0:
            return ""
        text = textpage.get_text_range(0, count) or ""
        if len(text) != count:
            # Désalignement (paires de substitution hors BMP) : on retombe sur
            # une lecture caractère par caractère, plus lente mais exacte.
            text = "".join((textpage.get_text_range(i, 1) or " ")[:1] for i in range(count))
        return text

    @staticmethod
    def _range_rects(
        textpage, index: int, count: int, height: float
    ) -> list[tuple[float, float, float, float]]:
        """Rects d'une plage de caractères, retournés en origine haut-gauche."""
        rects: list[tuple[float, float, float, float]] = []
        for k in range(textpage.count_rects(index, count)):
            left, bottom, right, top = textpage.get_rect(k)
            rects.append((float(left), height - float(top), float(right), height - float(bottom)))
        return rects

    @staticmethod
    def _group_words(
        textpage, text: str, height: float
    ) -> list[tuple[float, float, float, float, str]]:
        words: list[tuple[float, float, float, float, str]] = []
        buffer: list[str] = []
        box: list[float] | None = None

        def flush() -> None:
            nonlocal box
            word = "".join(buffer).strip()
            if word and box is not None:
                words.append((box[0], height - box[3], box[2], height - box[1], word))
            buffer.clear()
            box = None

        for index, char in enumerate(text):
            if char.isspace():
                flush()
                continue
            buffer.append(char)
            try:
                left, bottom, right, top = textpage.get_charbox(index)
            except Exception:  # pragma: no cover - défensif (caractère sans glyphe)
                continue
            if right <= left or top <= bottom:  # boîte dégénérée : ignorée
                continue
            if box is None:
                box = [float(left), float(bottom), float(right), float(top)]
            else:
                box[0] = min(box[0], float(left))
                box[1] = min(box[1], float(bottom))
                box[2] = max(box[2], float(right))
                box[3] = max(box[3], float(top))
        flush()
        return words

    @staticmethod
    def _group_lines(textpage, text: str) -> list[tuple[str, float]]:
        import pypdfium2.raw as pdfium_c

        lines: list[tuple[str, float]] = []
        buffer: list[str] = []
        size = 0.0

        def flush() -> None:
            nonlocal size
            content = "".join(buffer).strip()
            if content:
                lines.append((content, size))
            buffer.clear()
            size = 0.0

        for index, char in enumerate(text):
            if char in ("\r", "\n"):
                flush()
                continue
            buffer.append(char)
            if char.isspace():
                continue
            try:
                size = max(size, float(pdfium_c.FPDFText_GetFontSize(textpage.raw, index)))
            except Exception:  # pragma: no cover - défensif
                continue
        flush()
        return lines
