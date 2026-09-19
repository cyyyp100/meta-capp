import sys
from pathlib import Path

import pytest

# Le code applicatif utilise des imports absolus (db, services, config, ui...).
# On ajoute le dossier `nwol/` au path comme le fait main.py.
NWOL_DIR = Path(__file__).resolve().parents[1]
if str(NWOL_DIR) not in sys.path:
    sys.path.insert(0, str(NWOL_DIR))


@pytest.fixture(autouse=True)
def no_semantic_search(monkeypatch):
    """La couche sémantique du RAG (services/pdf_rag) appelle Ollama : hors
    des tests, toujours. Un test qui la veut remplace `pdf_rag._embed` par un
    faux embedder (cf. tests/services/test_pdf_rag.py)."""
    from services import pdf_rag

    monkeypatch.setattr(pdf_rag, "_embed", lambda texts: None)
    monkeypatch.setattr(pdf_rag, "_EMBED_STATE", {"retry_at": 0.0, "failure": ""})


@pytest.fixture
def make_pdf():
    """Fabrique un PDF de test : une page par entrée de ``pages``.

    Chaque entrée est le texte de la page (chaîne vide = page blanche) ; un
    saut de ligne y ajoute une ligne. Le texte commence à 72 pt du bord haut.

    Écrit avec reportlab, PAS avec le moteur de lecture : une fixture doit
    rester indépendante de la bibliothèque qu'elle sert à tester (et
    pypdfium2 ne sait écrire du texte qu'avec un fichier de police fourni).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    def _make(path, pages, font_size: int = 12) -> str:
        _width, height = A4
        pdf = canvas.Canvas(str(path), pagesize=A4)
        for text in pages:
            pdf.setFont("Helvetica", font_size)
            y = height - 72
            for line in str(text).split("\n"):
                if line:
                    pdf.drawString(72, y, line)
                y -= font_size * 1.4
            pdf.showPage()
        pdf.save()
        return str(path)

    return _make
