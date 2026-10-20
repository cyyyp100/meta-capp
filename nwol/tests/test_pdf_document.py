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
from utils.text import fold_query

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
    # À l'horizontale, les deux chemins coïncident. À la verticale, la boîte du
    # calque couvre le corps de la police (`_char_box`) : elle contient le
    # glyphe que trouve la recherche, sans déborder d'une ligne de 12 pt.
    assert abs(word[0] - rect[0]) < 1.5 and abs(word[2] - rect[2]) < 1.5
    assert word[1] <= rect[1] + 0.01 and word[3] >= rect[3] - 0.01
    assert word[3] - word[1] < 12 * 1.3


def test_the_words_of_a_line_share_one_band(tmp_path, make_pdf):
    """La boîte serrée d'un glyphe varie d'un mot à l'autre (« ce » : hauteur
    d'x ; « expliciter » : de l'ascendante à la descendante) : le calque en
    tirait une bande médiane qui coupait les jambages, et la sélection tombait
    à côté du texte. Les boîtes de mots couvrent maintenant le corps de la
    police — la même bande pour toute la ligne, qui contient chaque glyphe."""
    path = make_pdf(tmp_path / "band.pdf", ["ce que nous allons expliciter"])
    with PdfDocument(path) as pdf:
        words = pdf.words(1)
        glyphs = {w[4]: pdf.search_text(1, w[4])[0] for w in words}
    assert {round(w[1], 2) for w in words} == {round(words[0][1], 2)}
    assert {round(w[3], 2) for w in words} == {round(words[0][3], 2)}
    for x0, y0, x1, y1, text in words:
        gx0, gy0, gx1, gy1 = glyphs[text]
        assert y0 <= gy0 + 0.01 and y1 >= gy1 - 0.01, text


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


# ── Recherche pliée (Ctrl/Cmd+F du lecteur) ──────────────────────────────────
#
# `search_text` (la recherche de PDFium) ne trouvait ni « equation » dans
# « Équation », ni un mot coupé en fin de ligne. `find_folded` cherche dans le
# texte PLIÉ (`folded_text`) et rend une liste de rects par occurrence.


def test_find_folded_ignores_accents_and_case(tmp_path, make_pdf):
    path = make_pdf(tmp_path / "accents.pdf", ["Une Équation différentielle, puis une equation."])
    with PdfDocument(path) as pdf:
        hits = pdf.find_folded(1, fold_query("ÉQUATION"))
    assert len(hits) == 2
    for rects in hits:
        assert len(rects) == 1  # une ligne, un rect
        x0, y0, x1, y1 = rects[0]
        assert x1 > x0 and y1 > y0
        assert abs(y0 - _TEXT_TOP_MARGIN) < 25  # origine haut-gauche, comme search_text
    assert hits[0][0][0] < hits[1][0][0]  # dans l'ordre du texte


def test_find_folded_crosses_an_end_of_line_hyphenation(tmp_path, make_pdf):
    """reportlab écrit « différen- » en fin de ligne : PDFium le lit U+FFFE,
    sans saut de ligne. Le mot se trouve entier, un rect par ligne."""
    path = make_pdf(tmp_path / "hyphen.pdf", ["Les équations différen-\ntielles ordinaires."])
    with PdfDocument(path) as pdf:
        assert "differentielles ordinaires" in pdf.folded_text(1)
        hits = pdf.find_folded(1, fold_query("différentielles"))
    assert len(hits) == 1
    first_line, second_line = hits[0]
    assert second_line[1] > first_line[3] - 1  # la seconde ligne est en dessous


def test_find_folded_collapses_whitespace_and_line_breaks(tmp_path, make_pdf):
    path = make_pdf(tmp_path / "spaces.pdf", ["La photosynthese convertit\nla   lumiere en energie."])
    with PdfDocument(path) as pdf:
        hits = pdf.find_folded(1, fold_query("convertit la lumiere"))
    assert len(hits) == 1 and len(hits[0]) == 2  # à cheval sur deux lignes


def test_find_folded_counts_what_folded_text_counts(tmp_path, make_pdf):
    """L'invariant du « 3 / 17 » : le total vient de `folded_text`, les
    occurrences surlignées de `find_folded` — ils ne peuvent pas diverger."""
    path = make_pdf(tmp_path / "count.pdf", [
        "Le lait, le lion et le leopard.\nLe le le : lele.\nDifféren-\ntielle et différentielle.", "",
    ])
    with PdfDocument(path) as pdf:
        for needle in ("le", "le le", "lele", "differentielle", "e", "absent"):
            assert pdf.folded_text(1).count(needle) == len(pdf.find_folded(1, needle)), needle
        assert pdf.folded_text(2) == "" and pdf.find_folded(2, "le") == []
        assert pdf.find_folded(99, "le") == [] and pdf.find_folded(1, "") == []
        assert len(pdf.find_folded(1, "le", limit=2)) == 2


def test_a_hyphenated_word_gives_two_words_one_per_line(tmp_path, make_pdf):
    """C1 : « différen-tielles » formait UN mot dont la boîte couvrait deux
    lignes — un rectangle de sélection haut comme le paragraphe."""
    path = make_pdf(tmp_path / "split.pdf", ["Les équations différen-\ntielles ordinaires."])
    with PdfDocument(path) as pdf:
        words = pdf.words(1)
    texts = [w[4] for w in words]
    assert "différen-" in texts and "tielles" in texts
    assert not any(chr(0xFFFE) in text for text in texts)
    first = words[texts.index("différen-")]
    second = words[texts.index("tielles")]
    for x0, y0, x1, y1, _text in (first, second):
        assert y1 - y0 < 12 * 1.5  # une ligne de 12 pt, pas deux
    assert second[1] > first[3] - 1


def _tex_accented_pdf(path) -> str:
    """Une ligne écrite comme TeX en codage OT1 : chaque accent est un glyphe à
    part, dessiné AVANT sa lettre et centré au-dessus (ou au-dessous, pour la
    cédille). Plus un accent grave de code, posé À CÔTÉ de ses lettres."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    size = 12
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setFont("Helvetica", size)
    y = A4[1] - _TEXT_TOP_MARGIN
    x = 72.0

    def width(text: str) -> float:
        return stringWidth(text, "Helvetica", size)

    def run(text: str) -> None:
        nonlocal x
        pdf.drawString(x, y, text)
        x += width(text)

    def accented(accent: str, letter: str) -> None:
        nonlocal x
        pdf.drawString(x + (width(letter) - width(accent)) / 2, y, accent)
        pdf.drawString(x, y, letter)
        x += width(letter)

    run("d")
    accented("´", "e")
    run("tails ")
    run("`ls` ")
    run("gr")
    accented("ˆ", "a")
    run("ce Commen")
    accented("¸", "c")
    run("ons")
    pdf.showPage()
    pdf.save()
    return str(path)


def test_accents_drawn_apart_are_recomposed(tmp_path):
    """Les vieux PDF LaTeX posent « ´ » au-dessus de « e » : PDFium extrayait
    « d´etails », que le carnet citait tel quel, qu'un double-clic coupait à
    l'accent, que Ctrl/Cmd+F ne trouvait pas (« ´ » se pliait en espace) et
    que le LLM lisait en morceaux. Recomposés partout — mots, texte de page,
    texte plié, recherche d'une citation —, sauf l'accent grave du code, posé
    à côté de ses lettres et non au-dessus."""
    path = _tex_accented_pdf(tmp_path / "ot1.pdf")
    with PdfDocument(path) as pdf:
        assert [w[4] for w in pdf.words(1)] == ["détails", "`ls`", "grâce", "Commençons"]
        assert pdf.raw_text(1).split() == ["détails", "`ls`", "grâce", "Commençons"]
        assert "details `ls` grace commencons" in pdf.folded_text(1)
        assert len(pdf.find_folded(1, "details")) == 1
        # La citation recomposée (celle que lit le LLM) se retrouve sur la page.
        assert pdf.search_text(1, "détails")
        assert pdf.search_text(1, "Commençons")


class _FakeTextPage:
    """Boîtes PDFium (origine bas-gauche) données à la main, par caractère."""

    def __init__(self, boxes):
        self.boxes = boxes

    def get_charbox(self, index, loose=False):
        return self.boxes[index]


# Une lettre de 5 pt de large et de haut, posée sur la ligne de base à x = 10.
_LETTER = (10.0, 0.0, 15.0, 5.0)


def test_the_geometry_decides_what_an_accent_belongs_to():
    above = (11.0, 6.0, 14.0, 8.0)   # au-dessus de la lettre
    beside = (5.0, 6.0, 9.0, 8.0)    # à gauche, sans la recouvrir
    below = (11.0, -2.0, 14.0, 0.5)  # sous la ligne de base
    merges = PdfDocument._accent_merges
    # Accent puis lettre (l'ordre de TeX) ; i sans point coiffé : « î ».
    assert merges(_FakeTextPage([above, _LETTER]), "ˆı") == {0: "", 1: "î"}
    # Lettre puis accent : la barre d'un conjugué, « Q¯ » → « Q̄ ».
    assert merges(_FakeTextPage([_LETTER, above]), "Q¯") == {0: "Q̄", 1: ""}
    # La cédille se pose dessous ; un accent aigu, jamais.
    assert merges(_FakeTextPage([below, _LETTER]), "¸c") == {0: "", 1: "ç"}
    assert merges(_FakeTextPage([below, _LETTER]), "´e") == {}
    # À côté de sa lettre, un accent reste ce qu'il est (« `ls` », « l´école »).
    assert merges(_FakeTextPage([beside, _LETTER]), "`l") == {}


def test_recomposed_accents_reach_the_bounded_reading():
    """La lecture bornée (celle du LLM) et l'indexée ne diffèrent que par des
    invisibles — blancs autour d'une formule, marqueur de césure U+0002 contre
    U+FFFE, glyphe sans Unicode : la recomposition passe de l'une à l'autre.
    Au moindre écart visible, la lecture bornée est rendue telle quelle."""
    carry = PdfDocument._carry_merges
    merges = {1: "", 2: "é"}
    assert carry("d´et\x02ail", "d´et\r\n ￾ail", merges) == "dét\x02ail"
    assert carry("d´etail", "x´etail", merges) == "d´etail"
