import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import db
    from db import close_connection

    close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nwol.db"))
    from db.schema import initialize_schema

    initialize_schema()
    yield
    close_connection()


def test_create_list_and_filter(fresh_db):
    from services.flashcards import create_flashcard, list_flashcards

    cid = create_flashcard(front="2+2 ?", back="4", tags=["maths"], difficulty=1)
    assert isinstance(cid, int) and cid > 0

    cards = list_flashcards()
    assert len(cards) == 1
    card = cards[0]
    assert card["front"] == "2+2 ?"
    assert card["back"] == "4"
    assert "maths" in card["tags"]
    assert card["difficulty"] == 1
    assert card["source"] == "manual"

    # Le filtre par difficulté restreint la liste.
    assert len(list_flashcards(difficulty=1)) == 1
    assert len(list_flashcards(difficulty=3)) == 0


def test_existing_tags_aggregates(fresh_db):
    from services.flashcards import create_flashcard, existing_tags

    create_flashcard(front="a", back="b", tags=["algèbre", "maths"])
    create_flashcard(front="c", back="d", tags=["maths", "géométrie"])
    tags = existing_tags()
    assert set(tags) >= {"algèbre", "maths", "géométrie"}


def test_review_updates_due_date(fresh_db):
    from db.flashcards import get_flashcard
    from services.flashcards import create_flashcard, review_flashcard

    cid = create_flashcard(front="q", back="r")
    before = get_flashcard(cid)
    review_flashcard(cid, "correct")
    after = get_flashcard(cid)
    assert after["review_count"] == before["review_count"] + 1
    assert after["last_verdict"] == "correct"
    # Verdict "correct" => intervalle ×2.5 (s'allonge).
    assert float(after["interval_days"]) > float(before["interval_days"])


def test_delete_batch(fresh_db):
    from services.flashcards import create_flashcard, delete_flashcards, list_flashcards

    ids = [create_flashcard(front=f"q{i}", back=f"r{i}") for i in range(3)]
    removed = delete_flashcards(ids[:2])
    assert removed == 2
    remaining = list_flashcards()
    assert len(remaining) == 1
    assert remaining[0]["id"] == ids[2]


def test_fallback_tags_no_llm(fresh_db):
    from services.flashcards import fallback_tags

    tags = fallback_tags("Théorème de Pythagore", "a² + b² = c²", existing_tags=[])
    assert isinstance(tags, list)
    assert all(isinstance(tag, str) for tag in tags)


# ── Cartes automatiques : la politique du service ───────────────────────────

def test_auto_flashcard_is_created_for_a_good_answer(fresh_db):
    from services.flashcards import create_auto_flashcard, list_flashcards

    card = {"front": "What is transfer learning?", "back": "Reusing a trained model.", "tags": ["ml"]}
    assert create_auto_flashcard(card, verdict="correct", question_id=None, document_id=None, session_id=None)
    (saved,) = list_flashcards()
    assert saved["source"] == "auto" and saved["front"] == card["front"]
    # Une réponse fausse n'en crée pas, une carte déjà connue n'est pas annoncée.
    other = {"front": "What is fine-tuning?", "back": "Training further."}
    assert not create_auto_flashcard(other, verdict="incorrect", question_id=None, document_id=None, session_id=None)
    assert not create_auto_flashcard(card, verdict="partial", question_id=None, document_id=None, session_id=None)
    assert len(list_flashcards()) == 1


@pytest.mark.parametrize("card", [
    {"front": "When does transfer learning fail, according to the text?", "back": "Always."},
    {"front": "Which algorithm is the most stable?", "back": "Reptile, as shown in Table 3.5."},
    {"front": "Quels biais sont mentionnés dans le texte ?", "back": "Les fuites entre patients."},
])
def test_auto_flashcard_that_needs_the_document_is_refused(fresh_db, card):
    from services.flashcards import create_auto_flashcard, list_flashcards

    assert not create_auto_flashcard(card, verdict="correct", question_id=None, document_id=None, session_id=None)
    assert list_flashcards() == []


def test_explicit_flashcard_is_not_filtered(fresh_db):
    """« + Flashcard » est le choix de l'élève : il passe tel quel."""
    from services.flashcards import create_flashcard, list_flashcards

    create_flashcard(front="Quels biais sont mentionnés dans le texte ?", back="Les fuites.")
    assert len(list_flashcards()) == 1


def test_figure_and_connection_questions_never_make_a_card():
    from config import question_types

    assert not question_types.flashcard_eligible("visualization")
    assert not question_types.flashcard_eligible("connection")
    assert question_types.flashcard_eligible("comprehension")


# ── Sas d'entrée : le tirage d'échauffement ─────────────────────────────────
#
# Trois défauts d'origine, tous ramenant l'échauffement aux cartes les plus
# récentes : un `LIMIT 60` sur `created_at DESC`, une demi-vie de récence de 7
# jours, et un `random.choices` AVEC remise dont les collisions étaient rebouchées
# dans l'ordre de récence.

def _seed_cards(n: int, **kwargs) -> list[int]:
    from services.flashcards import create_flashcard

    prefix = kwargs.pop("prefix", "q")
    return [create_flashcard(front=f"{prefix}{i}", back=f"r{i}", **kwargs) for i in range(n)]


def _make_due(*card_ids: int, days: int = 3) -> None:
    from datetime import datetime, timedelta

    from db import get_connection

    with get_connection() as conn:
        for offset, card_id in enumerate(card_ids):
            conn.execute(
                "UPDATE flashcards SET due_at=? WHERE id=?",
                ((datetime.now() - timedelta(days=days + offset)).strftime("%Y-%m-%d %H:%M:%S"), card_id),
            )


def _document(name: str, subject: str | None) -> int:
    from db import get_connection

    with get_connection() as conn:
        return conn.execute(
            "INSERT INTO documents (path, filename, page_count, subject) VALUES (?, ?, 1, ?)",
            (f"/tmp/{name}", name, subject),
        ).lastrowid


def test_session_start_reaches_beyond_the_sixty_newest(fresh_db):
    """Une carte hors des 60 plus récentes doit pouvoir sortir en échauffement."""
    from services.flashcards import session_start_cards

    ids = _seed_cards(100)
    oldest_forty = set(ids[:40])  # créées en premier => hors des 60 plus récentes

    seen: set[int] = set()
    for _ in range(60):
        seen.update(card["id"] for card in session_start_cards(limit=5))
    # Avant : l'intersection était vide, quel que soit le nombre de tirages.
    assert seen & oldest_forty


def test_session_start_never_returns_the_same_card_twice(fresh_db):
    """Tirage sans remise : plus de doublon à réparer, donc plus de rebouchage biaisé."""
    from services.flashcards import session_start_cards

    _seed_cards(8)
    for _ in range(40):
        cards = session_start_cards(limit=5)
        ids = [card["id"] for card in cards]
        assert len(ids) == len(set(ids))
        assert len(ids) == 5


def test_session_start_damps_cards_just_reviewed(fresh_db):
    """`last_reviewed` est écrit par l'échauffement lui-même : il doit être lu."""
    from services.flashcards import review_flashcard, session_start_cards

    ids = _seed_cards(20)
    just_seen = set(ids[:5])
    for cid in just_seen:
        review_flashcard(cid, "partial")  # ce que fait WarmUp sur chaque carte montrée

    hits = 0
    for _ in range(60):
        hits += sum(card["id"] in just_seen for card in session_start_cards(limit=5))
    # Tirage neutre : 5 cartes sur 20 pour 5 places => ~75 sur 60 tours.
    # Amorties à FLASHCARD_REVIEW_FLOOR, elles doivent nettement reculer,
    # sans disparaître (amortir, pas exclure).
    assert 0 < hits < 45, f"cartes déjà vues servies {hits} fois"


def test_session_start_returns_everything_when_the_stock_is_small(fresh_db):
    from services.flashcards import session_start_cards

    _seed_cards(3)
    assert len(session_start_cards(limit=5)) == 3


def test_session_start_handles_an_empty_library(fresh_db):
    from services.flashcards import session_start_cards

    assert session_start_cards(limit=5) == []


# ── Sas d'entrée : la matière d'abord, la date ensuite ──────────────────────

def test_due_cards_of_the_subject_come_first(fresh_db):
    """Dans la matière du document, la répétition espacée passe avant le tirage
    pondéré — et une carte due d'une autre discipline ne lui passe pas devant."""
    from services.flashcards import session_start_cards

    doc = _document("cours.pdf", "informatique")
    ids = _seed_cards(30, document_id=doc)
    elsewhere = _seed_cards(3, prefix="physique", document_id=_document("meca.pdf", "physique"))
    overdue = ids[0]
    _make_due(*elsewhere, days=10)  # plus en retard, mais d'une autre discipline
    _make_due(overdue)
    for _ in range(10):
        cards = session_start_cards(doc, limit=5)
        assert cards[0]["id"] == overdue
        assert not {card["id"] for card in cards} & set(elsewhere)


def test_a_due_language_card_is_never_served_for_another_subject(fresh_db):
    """Des cartes de turc en retard ne remplissent jamais le sas d'un cours
    d'informatique : il se complète avec les autres disciplines, jamais une
    autre langue."""
    from services.flashcards import session_start_cards

    doc = _document("ml.pdf", "informatique")
    turkish = _seed_cards(4, prefix="Bonjour en turc ", source="lang_vocab", language="turc")
    _make_due(*turkish)
    physics = _seed_cards(2, prefix="physique", document_id=_document("meca.pdf", "physique"))
    loose = _seed_cards(2, prefix="libre")  # carte sans matière
    for _ in range(10):
        served = {card["id"] for card in session_start_cards(doc, limit=5)}
        assert not served & set(turkish)
        assert served == set(physics) | set(loose)
    # Matière du document encore inconnue : pas de langue non plus.
    unknown = _document("pas-encore-lu.pdf", None)
    assert not {card["id"] for card in session_start_cards(unknown, limit=5)} & set(turkish)


def test_a_language_document_serves_the_language_module_cards_first(fresh_db):
    """Un document de turc ouvre sur les cartes du module Langues en turc,
    puis complète avec les autres disciplines — jamais une autre langue."""
    from services.flashcards import session_start_cards

    doc = _document("turkce.pdf", "turc")
    turkish = _seed_cards(3, prefix="mot ", source="lang_feuilleton", language="turc")
    english = _seed_cards(3, prefix="word ", source="lang_feuilleton", language="anglais")
    physics = _seed_cards(4, prefix="physique", document_id=_document("meca.pdf", "physique"))
    _make_due(*physics)
    for _ in range(10):
        cards = session_start_cards(doc, limit=5)
        assert {card["id"] for card in cards[:3]} == set(turkish)
        assert {card["id"] for card in cards[3:]} <= set(physics)
        assert not {card["id"] for card in cards} & set(english)


def test_a_card_of_the_subject_beats_a_due_card_of_another_discipline(fresh_db):
    from services.flashcards import session_start_cards

    doc = _document("cours.pdf", "informatique")
    (mine,) = _seed_cards(1, prefix="algo", document_id=_document("algo.pdf", "informatique"))
    (theirs,) = _seed_cards(1, prefix="physique", document_id=_document("meca.pdf", "physique"))
    _make_due(theirs)
    assert [card["id"] for card in session_start_cards(doc, limit=1)] == [mine]
    assert [card["id"] for card in session_start_cards(doc, limit=5)] == [mine, theirs]


def test_a_card_keeps_its_subject_once_its_document_is_deleted(fresh_db):
    """La carte d'un cours supprimé reste une carte de sa matière : elle ouvre
    encore le sas d'un autre cours de la même matière."""
    from db.documents import delete_document
    from services.flashcards import session_start_cards

    old = _document("ancien-cours.pdf", "informatique")
    (card,) = _seed_cards(1, prefix="algo", document_id=old)
    _seed_cards(10, prefix="physique", document_id=_document("meca.pdf", "physique"))
    assert delete_document(old)
    doc = _document("nouveau-cours.pdf", "informatique")
    for _ in range(10):
        cards = session_start_cards(doc, limit=5)
        assert cards[0]["id"] == card and cards[0]["card_subject"] == "informatique"
