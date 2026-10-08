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


@pytest.fixture(autouse=True)
def no_real_generation(monkeypatch):
    """Aucune génération ne part vers un vrai Ollama pendant les tests.

    Sans ce garde, le résultat dépendait de la machine. Ollama lancé : la suite
    générait pour de vrai (lente, non déterministe). Ollama absent : chaque
    tentative échouait — instantanément sous Linux, mais en ~2 s sous Windows,
    qui retente le SYN avant d'accepter le refus. Les tâches de fond laissées
    par un test (fiche de document : 4 tentatives) occupaient alors le worker
    LLM UNIQUE bien après sa fin, et les tests suivants qui attendent ce worker
    échouaient en CI Windows. La panne est désormais immédiate partout, et les
    chemins de repli sont ceux que la CI a toujours vérifiés.

    On coupe sous `llm_provider` : un test qui remplace `_call_ollama` garde la
    main, et `test_llm_cancel.py` appelle `_call_ollama_http` directement contre
    son propre faux serveur."""
    from llm import ollama_client
    from services import llm_provider, orchestrator

    def _offline(*_args, **_kwargs):
        raise RuntimeError("Ollama indisponible (tests)")

    monkeypatch.setattr(llm_provider, "_ollama_generate", _offline)
    monkeypatch.setattr(ollama_client, "is_ollama_available", lambda: False)
    monkeypatch.setattr(orchestrator, "is_ollama_available", lambda: False)


@pytest.fixture(autouse=True)
def no_startup_backfill(monkeypatch):
    """Le démarrage du serveur (lifespan) lance le calcul des empreintes dans un
    thread (services/relink). Ce thread survivrait au test qui l'a lancé : il
    pourrait écrire dans la VRAIE base une fois `db.DB_PATH` rétabli. Coupé
    partout ; le test qui le vérifie reçoit la vraie fonction par cette fixture."""
    from services import relink

    real = relink.backfill_content_hashes
    monkeypatch.setattr(relink, "backfill_content_hashes", lambda: 0)
    return real


@pytest.fixture(autouse=True, scope="session")
def no_real_logs_or_assets(tmp_path_factory):
    """En dev, le journal (`logs/nwol.log`) et les assets (`nwol/assets` : cache
    des pages rendues, PDF de démo) sont ceux de l'utilisateur. Un test qui
    appelait `POST /api/data/purge` les supprimait — le journal d'une app
    lancée à côté disparaissait, elle continuant d'écrire dans un fichier
    effacé —, ceux qui appellent `setup_logging()` y versaient leur sortie, et
    le rendu des pages remplissait le vrai cache. Toute la session vise un
    dossier temporaire ; un test qui veut le sien le remplace par-dessus."""
    from config import logging_config, settings
    from pdf_viewer import page_renderer
    from services import data_export, onboarding

    root = tmp_path_factory.mktemp("app-data")
    with pytest.MonkeyPatch.context() as mp:
        for module in (settings, logging_config, data_export):
            mp.setattr(module, "LOG_FILE", str(root / "logs" / "nwol.log"))
        for module in (settings, page_renderer, onboarding, data_export):
            mp.setattr(module, "ASSETS_DIR", str(root / "assets"))
        yield


@pytest.fixture(autouse=True)
def no_startup_relaunch(monkeypatch):
    """Le démarrage du serveur (lifespan) relance en thread les épisodes de
    langue en attente (services/lang_runs.on_startup). Ce thread survivrait au
    test qui l'a lancé : il pourrait viser la VRAIE base une fois `db.DB_PATH`
    rétabli, et un vrai Ollama. Coupé partout ; le test qui le vérifie reçoit
    la vraie fonction par cette fixture."""
    from services import lang_runs

    real = lang_runs.relaunch_pending_episodes
    monkeypatch.setattr(lang_runs, "relaunch_pending_episodes", lambda: [])
    return real


@pytest.fixture(autouse=True)
def reference_throughput():
    """Les budgets temps dépendent du débit MESURÉ (llm/throughput) : un test
    qui simule un appel lent ou expiré ne doit pas étirer ceux des suivants —
    ni leur laisser l'échéance d'une tâche (`_TASK_DEADLINE`, par thread)."""
    from llm import ollama_client, throughput

    throughput.reset()
    yield
    throughput.reset()
    ollama_client._TASK_DEADLINE.value = None


@pytest.fixture(autouse=True)
def not_in_browser_mode():
    """Un test qui active le mode navigateur (services/lifecycle) ne le laisse
    pas aux suivants : « Quitter » y appellerait sa fausse fonction d'arrêt."""
    from services import lifecycle

    lifecycle.reset()
    yield
    lifecycle.reset()


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
