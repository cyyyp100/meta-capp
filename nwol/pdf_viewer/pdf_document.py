# pdf_viewer/pdf_document.py — Accès PDF léger (pypdfium2) pour le lecteur page-par-page
from __future__ import annotations

import logging
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from pdf_viewer.engine import PDFIUM_LOCK

logger = logging.getLogger("pdf_viewer.document")

# Accents posés en glyphe à part : les PDF LaTeX en codage OT1 dessinent « é »
# comme un « ´ » placé au-dessus d'un « e », et PDFium extrait les deux, dans
# l'ordre de TeX — « d´etails », « `a », « grˆace », « maˆıtre » (i sans point),
# « Commen¸cons ». Chacun avec sa marque combinante (noms de la liste des
# glyphes Adobe : acute, grave, circumflex…).
_SPACING_ACCENTS = {
    "´": "́",  # ´ aigu
    "`": "̀",  # ` grave
    "ˆ": "̂",  # ˆ circonflexe
    "¨": "̈",  # ¨ tréma
    "˜": "̃",  # ˜ tilde
    "¸": "̧",  # ¸ cédille
    "˛": "̨",  # ˛ ogonek
    "ˇ": "̌",  # ˇ caron
    "˘": "̆",  # ˘ brève
    "˙": "̇",  # ˙ point suscrit
    "˚": "̊",  # ˚ rond
    "¯": "̄",  # ¯ macron
    "˝": "̋",  # ˝ double aigu
}
# Ceux-là se posent SOUS la lettre.
_ACCENTS_BELOW = frozenset({"¸", "˛"})
# Une lettre accentuée a perdu son point : « ˆı » est « î ».
_DOTLESS = {"ı": "i", "ȷ": "j"}
# Un accent COIFFE une lettre quand au moins la moitié de sa largeur est
# au-dessus d'elle — au-delà de 40 % de sa hauteur (en deçà pour une cédille).
# Posé à côté, il reste ce qu'il est : un accent grave qui ouvre du code
# (« `ls` »), une apostrophe tapée « ´ », le « ~ » d'une adresse.
_ACCENT_MIN_OVERLAP = 0.5
_ACCENT_MIN_RISE = 0.4


def _invisible(char: str) -> bool:
    """Blanc, caractère de contrôle ou non-caractère : rien à apparier entre
    les deux lectures de PDFium (cf. `PdfDocument._carry_merges`). Les
    marqueurs de césure en sont (U+FFFE dans la lecture indexée, U+0002 dans
    la bornée), comme les glyphes sans Unicode qu'une formule laisse en U+0002
    d'un côté et en espace de l'autre."""
    return char.isspace() or unicodedata.category(char) in ("Cc", "Cn")

# Boîte « loose » d'un caractère (cf. `PdfDocument._char_box`) : elle doit
# contenir le glyphe à cette tolérance près, et ne pas dépasser ce multiple de
# sa plus grande dimension — au-delà, les métriques de la police sont
# fantaisistes et la boîte du glyphe fait foi. Le corps d'une lettre courante
# fait au plus ~2,2 fois sa hauteur d'x ; un point ou un tiret, beaucoup plus,
# et retombent donc sur leur glyphe (la bande de la ligne les reprend côté
# lecteur).
_LOOSE_TOLERANCE_PT = 1.0
_LOOSE_MAX_RATIO = 3.0


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
        """Texte brut d'une page (contexte secondaire pour le LLM), accents
        recomposés (`_accent_merges`)."""
        try:
            with self._page(page_number) as page:
                if page is None:
                    return ""
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded() or ""
                    indexed = self._indexed_text(textpage)
                    merges = self._accent_merges(textpage, indexed)
                    if merges:
                        text = self._carry_merges(text, indexed, merges)
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
        if not rects:
            # PDFium ne cherche que le texte tel qu'il l'extrait. Une citation
            # recomposée (« détails » sur une page qui dit « d´etails »), ou qui
            # n'en diffère que par les accents, la casse ou une césure, se
            # cherche alors dans le texte plié — le même que Ctrl/Cmd+F.
            from utils.text import fold_query

            folded = fold_query(needle)
            if folded:
                rects = [rect for hit in self.find_folded(page_number, folded) for rect in hit]
        return rects

    def folded_text(self, page_number: int) -> str:
        """Texte plié d'une page (`utils.text.fold_with_map`) : sans accents,
        en minuscules, blancs réduits, mots coupés en fin de ligne recollés.

        C'est le texte où la recherche du lecteur (Ctrl/Cmd+F) COMPTE les
        occurrences, et `find_folded` les localise dans le même : le total
        annoncé et les occurrences surlignées viennent d'une seule lecture."""
        from utils.text import fold_with_map

        try:
            with self._page(page_number) as page:
                if page is None:
                    return ""
                textpage = page.get_textpage()
                try:
                    return fold_with_map(self._composed(textpage)[0])[0]
                finally:
                    textpage.close()
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("folded_text page %s: %s", page_number, exc)
            return ""

    def find_folded(
        self, page_number: int, needle: str, limit: int | None = None
    ) -> list[list[tuple[float, float, float, float]]]:
        """Occurrences de `needle` (DÉJÀ plié, cf. `utils.text.fold_query`) dans
        `folded_text(page)` → UNE LISTE DE RECTS PAR OCCURRENCE, un rect par
        ligne, en points PDF origine haut-gauche.

        Contrairement à `search_text` (la recherche de PDFium), « equation »
        trouve « Équation » et un mot coupé en fin de ligne se trouve entier.
        Invariant : `folded_text(p).count(n) == len(find_folded(p, n))` — une
        occurrence sans boîte (caractères sans glyphe) garde sa place, vide."""
        from utils.text import find_all, fold_with_map

        if not needle:
            return []
        try:
            with self._page(page_number) as page:
                if page is None:
                    return []
                height = float(page.get_size()[1])
                textpage = page.get_textpage()
                try:
                    composed, origin = self._composed(textpage)
                    folded, mapping = fold_with_map(composed)
                    hits: list[list[tuple[float, float, float, float]]] = []
                    for start in find_all(folded, needle, limit):
                        first = origin[mapping[start]]
                        last = origin[mapping[start + len(needle) - 1]]
                        hits.append(self._range_rects(textpage, first, last - first + 1, height))
                    return hits
                finally:
                    textpage.close()
        except Exception as exc:  # pragma: no cover - défensif
            logger.debug("find_folded page %s: %s", page_number, exc)
            return []

    def words(self, page_number: int) -> list[tuple[float, float, float, float, str]]:
        """Boîtes de mots d'une page → (x0, y0, x1, y1, mot) en points PDF.

        Alimente le calque de texte transparent du lecteur web (sélection native
        par-dessus l'image rendue). Liste vide si page invalide ou sans texte.

        PDFium n'expose que des caractères : on regroupe les suites non-blanches
        et on unit leurs boîtes. L'ordre reste celui du flux de contenu, comme
        le faisait ``get_text("words")``. Les boîtes couvrent le CORPS de la
        police (cf. `_char_box`) : tous les mots d'une ligne partagent la même
        bande, jambages compris.
        """
        try:
            with self._page(page_number) as page:
                if page is None:
                    return []
                height = float(page.get_size()[1])
                textpage = page.get_textpage()
                try:
                    text = self._indexed_text(textpage)
                    return self._group_words(textpage, text, height, self._accent_merges(textpage, text))
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
                    return self._group_lines(textpage, text, self._accent_merges(textpage, text))
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
    def _accent_merges(textpage, text: str) -> dict[int, str]:
        """Accents posés en glyphe à part (`_SPACING_ACCENTS`) → remplacements,
        par index PDFium : l'accent disparaît (« »), la lettre qu'il coiffe
        devient la lettre accentuée (« ´ » + « e » → « é », « ˆ » + « ı » →
        « î », « Q » + « ¯ » → « Q̄ »).

        Le texte seul ne suffit pas à décider : « `a » est « à » sous un vieux
        PDF LaTeX, mais du code dans un cours de programmation. C'est la
        géométrie qui tranche (`_accent_sits_on`) — un accent coiffe sa
        lettre, un caractère ordinaire se pose à côté. La lettre est la
        suivante (l'ordre de TeX), à défaut la précédente."""
        merges: dict[int, str] = {}
        for i, char in enumerate(text):
            mark = _SPACING_ACCENTS.get(char)
            if mark is None:
                continue
            for j in (i + 1, i - 1):
                if not 0 <= j < len(text) or j in merges or not text[j].isalpha():
                    continue
                if PdfDocument._accent_sits_on(textpage, i, j, below=char in _ACCENTS_BELOW):
                    merges[i] = ""
                    merges[j] = unicodedata.normalize("NFC", _DOTLESS.get(text[j], text[j]) + mark)
                    break
        return merges

    @staticmethod
    def _accent_sits_on(textpage, accent: int, letter: int, below: bool) -> bool:
        """L'accent `accent` coiffe-t-il la lettre `letter` (boîtes serrées) ?"""
        try:
            a_left, a_bottom, a_right, a_top = (float(v) for v in textpage.get_charbox(accent))
            l_left, l_bottom, l_right, l_top = (float(v) for v in textpage.get_charbox(letter))
        except Exception:  # pragma: no cover - défensif (caractère sans glyphe)
            return False
        width = a_right - a_left
        height = l_top - l_bottom
        if width <= 0 or height <= 0 or l_right <= l_left:
            return False
        if min(a_right, l_right) - max(a_left, l_left) < width * _ACCENT_MIN_OVERLAP:
            return False
        rise = l_bottom + height * _ACCENT_MIN_RISE
        return a_top <= rise if below else a_bottom >= rise

    @staticmethod
    def _composed(textpage) -> tuple[str, list[int]]:
        """Le texte indexé, accents recomposés, et l'index PDFium de chacun de
        ses caractères — celui de la lettre pour une lettre accentuée. C'est le
        texte que plie la recherche (`folded_text`, `find_folded`) : les
        positions repliées remontent ainsi aux boîtes de PDFium."""
        text = PdfDocument._indexed_text(textpage)
        merges = PdfDocument._accent_merges(textpage, text)
        out: list[str] = []
        origin: list[int] = []
        for index, char in enumerate(text):
            for produced in merges.get(index, char):
                out.append(produced)
                origin.append(index)
        return "".join(out), origin

    @staticmethod
    def _carry_merges(bounded: str, indexed: str, merges: dict[int, str]) -> str:
        """Reporte dans la lecture bornée (`get_text_bounded`) les accents
        recomposés sur la lecture indexée.

        La bornée est celle que lit le LLM : elle n'a pas les blancs que
        l'indexée ajoute autour d'un exposant ou d'une formule (« composants
        5\\r\\n. La », « sin \\r\\nx »). Les deux ne diffèrent que par des
        caractères invisibles (`_invisible`) : les autres se répondent un à un,
        dans l'ordre. Au premier qui diffère, la lecture bornée est rendue
        telle quelle, sans recomposition."""
        visible = ((j, c) for j, c in enumerate(indexed) if not _invisible(c))
        out: list[str] = []
        for char in bounded:
            if _invisible(char):
                out.append(char)
                continue
            j, twin = next(visible, (-1, ""))
            if twin != char:
                return bounded
            out.append(merges.get(j, char))
        return "".join(out)

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
    def _char_box(textpage, index: int) -> tuple[float, float, float, float] | None:
        """Boîte d'un caractère pour le calque de sélection, en origine PDFium.

        La boîte serrée (`get_charbox`) est celle du glyphe : « ce » n'a que la
        hauteur d'x, « expliciter » va de l'ascendante à la descendante — sur
        une même ligne, des boîtes de 4,5 à 8,8 pt pour un corps de 10 pt.
        Le calque en tirait une bande médiane qui coupait les jambages, et la
        sélection comme les surlignages tombaient à côté du texte. La boîte
        « loose » couvre le corps entier de la police (ascendante → descendante,
        origine → avance) : la même pour tous les caractères d'une ligne.

        Elle n'est retenue que si elle est plausible : non dégénérée (PDFium la
        calcule à plat — un texte pivoté la donne vide), contenant le glyphe,
        et pas démesurée (métriques de police fantaisistes). Sinon, la boîte
        serrée. None : caractère sans boîte (ignoré, comme avant)."""
        try:
            left, bottom, right, top = (float(v) for v in textpage.get_charbox(index))
        except Exception:  # pragma: no cover - défensif (caractère sans glyphe)
            return None
        if not (right > left and top > bottom):
            return None
        try:
            l_left, l_bottom, l_right, l_top = (float(v) for v in textpage.get_charbox(index, loose=True))
        except Exception:  # pragma: no cover - défensif
            return left, bottom, right, top
        plausible = (
            l_right > l_left
            and l_top > l_bottom
            and l_left <= left + _LOOSE_TOLERANCE_PT
            and l_right >= right - _LOOSE_TOLERANCE_PT
            and l_bottom <= bottom + _LOOSE_TOLERANCE_PT
            and l_top >= top - _LOOSE_TOLERANCE_PT
            and l_top - l_bottom <= _LOOSE_MAX_RATIO * max(top - bottom, right - left)
        )
        if plausible:
            return l_left, l_bottom, l_right, l_top
        return left, bottom, right, top

    @staticmethod
    def _group_words(
        textpage, text: str, height: float, merges: dict[int, str] | None = None
    ) -> list[tuple[float, float, float, float, str]]:
        from utils.text import HYPHENATION_MARKERS

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
            # Césure : PDFium remplace le tiret ET le saut de ligne par ce
            # marqueur. Sans coupure ici, « différen- / tielles » formait UN mot
            # dont la boîte couvrait deux lignes — un rectangle de sélection
            # grand comme le paragraphe. Le tiret, avec sa propre boîte, clôt le
            # premier morceau ; le second commence la ligne suivante.
            hyphen = char in HYPHENATION_MARKERS
            # Accent recomposé : il disparaît du mot, sa lettre devient la
            # lettre accentuée — mais sa boîte reste dans celle du mot.
            buffer.append("-" if hyphen else (merges or {}).get(index, char))
            char_box = PdfDocument._char_box(textpage, index)
            if char_box is not None:  # caractère sans boîte : ignoré
                left, bottom, right, top = char_box
                if box is None:
                    box = [left, bottom, right, top]
                else:
                    box[0] = min(box[0], left)
                    box[1] = min(box[1], bottom)
                    box[2] = max(box[2], right)
                    box[3] = max(box[3], top)
            if hyphen:
                flush()
        flush()
        return words

    @staticmethod
    def _group_lines(textpage, text: str, merges: dict[int, str] | None = None) -> list[tuple[str, float]]:
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
            buffer.append((merges or {}).get(index, char))
            if char.isspace():
                continue
            try:
                size = max(size, float(pdfium_c.FPDFText_GetFontSize(textpage.raw, index)))
            except Exception:  # pragma: no cover - défensif
                continue
        flush()
        return lines
