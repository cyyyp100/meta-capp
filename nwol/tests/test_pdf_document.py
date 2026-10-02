"""Contrat de `pdf_viewer.PdfDocument` — le seul point de contact avec PDFium.

Le test qui compte ici est celui de l'ORIENTATION. PDFium rend ses boîtes en
origine bas-gauche (y vers le haut) ; le SVG du lecteur, les masques de rappel
libre et les surlignages **déjà persistés en base** sont en origine haut-gauche
(y vers le bas). L'inversion vit dans `PdfDocument` et nulle part ailleurs :
si elle saute, les surlignages se posent au symétrique vertical du texte, sans
qu'aucun autre test ne s'en aperçoive.
"""

import threading

from pdf_viewer.pdf_document import PdfDocument

# `make_pdf` écrit la première ligne à 72 pt du bord HAUT d'une page A4 (842 pt).
_A4_HEIGHT = 842.0
_TEXT_TOP_MARGIN = 72.0


def test_page_count_and_sizes(tmp_path, make_pdf):
    path = make_pdf(tmp_path / "sizes.pdf", ["Page une", "Page deux"])
    with PdfDocument(path) as pdf:
        assert pdf.page_count() == 2
        sizes = pdf.page_sizes()
    assert len(sizes) == 2
    for width, height in sizes:
        assert 500 < width < 650      # A4 ≈ 595 pt
        assert 800 < height < 900     # A4 ≈ 842 pt


def test_raw_text_reads_the_page_and_normalises_newlines(tmp_path, make_pdf):
    path = make_pdf(tmp_path / "text.pdf", ["Premiere ligne\nSeconde ligne", "Autre page"])
    with PdfDocument(path) as pdf:
        first = pdf.raw_text(1)
        assert "Premiere ligne" in first
        assert "Seconde ligne" in first
        assert "\r" not in first  # PDFium sépare en CRLF, l'app attend du LF
        assert "Autre page" in pdf.raw_text(2)
        # Hors limites : vide, jamais une exception.
        assert pdf.raw_text(0) == ""
        assert pdf.raw_text(99) == ""


def test_search_text_returns_top_left_rects(tmp_path, make_pdf):
    """Le rect d'un texte écrit EN HAUT de page doit avoir un y0 PETIT."""
    path = make_pdf(tmp_path / "search.pdf", ["La photosynthese convertit la lumiere."])
    with PdfDocument(path) as pdf:
        rects = pdf.search_text(1, "photosynthese")
    assert len(rects) == 1
    x0, y0, x1, y1 = rects[0]
    assert x1 > x0 and y1 > y0                       # rect non dégénéré, y croissant vers le bas
    assert abs(y0 - _TEXT_TOP_MARGIN) < 25           # ~72 pt du HAUT, pas du bas
    assert y1 < _A4_HEIGHT / 2                       # et surtout pas dans la moitié basse


def test_search_text_is_case_insensitive_and_crosses_line_breaks(tmp_path, make_pdf):
    path = make_pdf(tmp_path / "multiline.pdf", ["La photosynthese convertit\nla lumiere en energie."])
    with PdfDocument(path) as pdf:
        assert pdf.search_text(1, "PHOTOSYNTHESE")
        # Une occurrence à cheval sur deux lignes : un rect par ligne.
        assert len(pdf.search_text(1, "convertit la lumiere")) == 2
        assert pdf.search_text(1, "absent du document") == []
        assert pdf.search_text(1, "") == []


def test_words_are_grouped_and_oriented_top_left(tmp_path, make_pdf):
    path = make_pdf(tmp_path / "words.pdf", ["Bonjour Meta Capp"])
    with PdfDocument(path) as pdf:
        words = pdf.words(1)
    assert [w[4] for w in words] == ["Bonjour", "Meta", "Capp"]
    for x0, y0, x1, y1, _text in words:
        assert x1 > x0 and y1 > y0
        assert abs(y0 - _TEXT_TOP_MARGIN) < 25       # même orientation que search_text
    # Les mots d'une même ligne se suivent de gauche à droite.
    assert words[0][0] < words[1][0] < words[2][0]


def test_words_and_search_agree_on_the_same_word(tmp_path, make_pdf):
    """Garde-fou : les deux chemins de coordonnées ne doivent pas diverger.

    Le calque de sélection (`words`) et le surlignage d'une citation
    (`search_text`) doivent placer le même mot au même endroit, sinon
    surligner à la souris et surligner une citation de Clikoda ne donnent pas
    le même rect.
    """
    path = make_pdf(tmp_path / "agree.pdf", ["Bonjour Meta Capp"])
    with PdfDocument(path) as pdf:
        word = next(w for w in pdf.words(1) if w[4] == "Meta")
        rect = pdf.search_text(1, "Meta")[0]
    for from_words, from_search in zip(word[:4], rect):
        assert abs(from_words - from_search) < 2.0


def test_line_sizes_expose_a_bigger_heading(tmp_path, make_pdf):
    """La détection de chapitres repose sur des tailles RELATIVES."""
    big = make_pdf(tmp_path / "big.pdf", ["Chapitre premier"], font_size=24)
    small = make_pdf(tmp_path / "small.pdf", ["Chapitre premier"], font_size=10)
    with PdfDocument(big) as pdf:
        heading = pdf.line_sizes(1)
    with PdfDocument(small) as pdf:
        body = pdf.line_sizes(1)
    assert heading and body
    assert heading[0][0] == body[0][0] == "Chapitre premier"
    assert heading[0][1] > body[0][1] * 1.15  # au-delà de _HEADING_SIZE_RATIO


def test_concurrent_access_is_serialised(tmp_path, make_pdf):
    """PDFium n'est pas thread-safe : sans le verrou moteur, ceci CRASHE.

    Ce n'est pas une hypothèse. FastAPI exécute chaque endpoint synchrone dans
    un thread du pool, et le lecteur demande plusieurs pages en parallèle dès
    qu'on scrolle : sans `pdf_viewer/engine.py:PDFIUM_LOCK`, on obtient soit un
    « Data format error » sur un fichier valide, soit un `Abort trap: 6` qui
    emporte tout le backend.
    """
    from pdf_viewer import page_renderer

    path = make_pdf(tmp_path / "concurrent.pdf", [f"Page numero {n}" for n in range(1, 9)])
    failures: list[str] = []
    results: list[int] = []

    def worker(index: int) -> None:
        try:
            page = index % 8 + 1
            with PdfDocument(path) as pdf:
                assert pdf.page_count() == 8
                words = pdf.words(page)
                pdf.search_text(page, "Page")
                pdf.raw_text(page)
            page_renderer.render_page(path, page, 1.0 + index * 0.1)
            results.append(len(words))
        except Exception as exc:  # pragma: no cover - c'est le point du test
            failures.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert len(results) == 12
    assert all(count == 3 for count in results)  # « Page numero N »
    page_renderer.clear_page_cache(path)


def test_empty_page_degrades_silently(tmp_path, make_pdf):
    """Un PDF sans couche texte (scanné) : vide partout, jamais une exception."""
    path = make_pdf(tmp_path / "blank.pdf", [""])
    with PdfDocument(path) as pdf:
        assert pdf.raw_text(1).strip() == ""
        assert pdf.words(1) == []
        assert pdf.line_sizes(1) == []
        assert pdf.search_text(1, "quoi que ce soit") == []
        assert pdf.toc() == []
