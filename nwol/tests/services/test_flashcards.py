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
