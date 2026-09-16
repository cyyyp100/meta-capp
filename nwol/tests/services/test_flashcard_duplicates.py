"""Une flashcard n'existe qu'une fois — quel que soit le chemin qui la crée.

Avant la v29, rien ne l'empêchait : « + Flashcard » cliqué deux fois sous la
même réponse de Gemma, la même carte tapée deux fois, une carte auto créée à
la bonne réponse puis recréée à la main. Chaque doublon revenait deux fois en
échauffement et faussait la répétition espacée.
"""
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


def test_same_card_twice_is_one_card(fresh_db):
    from services.flashcards import create_flashcard, list_flashcards

    first = create_flashcard(front="Qu'est-ce que l'ADN ?", back="Le support de l'hérédité.")
    second = create_flashcard(front="Qu'est-ce que l'ADN ?", back="Le support de l'hérédité.")

    assert second == first
    assert len(list_flashcards()) == 1


def test_duplicates_are_compared_by_meaning_not_by_bytes(fresh_db):
    """Casse, accents et blancs ne font pas une carte différente."""
    from services.flashcards import create_flashcard, find_flashcard, list_flashcards

    first = create_flashcard(front="Qu'est-ce que  l'ADN ?", back="Le support de l'hérédité.")
    assert find_flashcard("qu'est-ce que l'adn ?", "le support de l'heredite.") == first
    assert create_flashcard(front="QU'EST-CE QUE L'ADN ?", back="le support de l'hérédité.") == first
    assert len(list_flashcards()) == 1


def test_different_cards_are_kept(fresh_db):
    from services.flashcards import create_flashcard, list_flashcards

    a = create_flashcard(front="Q", back="R1")
    b = create_flashcard(front="Q", back="R2")
    assert a != b
    assert len(list_flashcards()) == 2


def test_exchange_origin_is_the_key_not_the_llm_rewrite(fresh_db):
    """Le LLM réécrit différemment à chaque appel : c'est l'échange brut qui
    identifie la carte, sinon deux clics donnaient deux cartes."""
    from services.flashcards import create_flashcard, find_flashcard, list_flashcards

    origin = ("Pourquoi le ciel est bleu ?", "Diffusion de Rayleigh : le bleu est plus diffusé.")
    first = create_flashcard(front="Cause de la couleur du ciel ?", back="Diffusion de Rayleigh.", origin=origin)
    second = create_flashcard(front="Pourquoi voit-on le ciel bleu ?", back="La diffusion de Rayleigh.", origin=origin)

    assert second == first
    assert len(list_flashcards()) == 1
    # Le routeur regarde l'échange brut AVANT d'appeler le LLM.
    assert find_flashcard(*origin) == first


def test_deleted_card_can_be_created_again(fresh_db):
    from services.flashcards import create_flashcard, delete_flashcards, list_flashcards

    first = create_flashcard(front="Q", back="R")
    delete_flashcards([first])
    again = create_flashcard(front="Q", back="R")
    assert again != first
    assert len(list_flashcards()) == 1


def test_migration_removes_existing_duplicates_and_keeps_the_reviewed_one(tmp_path, monkeypatch):
    """Base d'avant la v29 : trois copies de la même carte, une seule révisée.
    C'est elle que la répétition espacée connaît — c'est elle qu'on garde."""
    import db
    from db import close_connection

    close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "old.db"))
    from db.schema import initialize_schema

    initialize_schema()
    conn = db.get_connection()
    with conn:
        conn.execute("DROP INDEX IF EXISTS idx_flashcards_dedup")
        for n in (1, 2, 3):
            conn.execute(
                "INSERT INTO flashcards (user_id, front, back, review_count) VALUES (1, 'Q', 'R', ?)",
                (5 if n == 2 else 0,),
            )
        conn.execute("INSERT INTO flashcards (user_id, front, back) VALUES (1, 'Autre', 'Carte')")
        conn.execute("DELETE FROM schema_version")
        conn.execute("INSERT INTO schema_version (version) VALUES (28)")

    initialize_schema()

    rows = db.get_connection().execute(
        "SELECT front, review_count FROM flashcards ORDER BY id"
    ).fetchall()
    assert [(r["front"], r["review_count"]) for r in rows] == [("Q", 5), ("Autre", 0)]
    close_connection()


def test_llm_rewrite_that_lands_on_an_existing_card_is_that_card(fresh_db):
    """La clé d'une carte d'échange est l'échange brut — mais si la réécriture
    du LLM retombe sur une carte que l'utilisateur a déjà (tapée à la main),
    c'est elle qu'on rend : deux textes identiques ne font pas deux cartes."""
    from services.flashcards import create_flashcard, list_flashcards

    manual = create_flashcard(front="Qu'est-ce que l'ADN ?", back="Le support de l'hérédité.")
    from_exchange = create_flashcard(
        front="qu'est-ce que l'ADN ?",
        back="Le support de l'hérédité.",
        origin=("Selon ce texte, l'ADN c'est quoi ?", "C'est le support de l'hérédité, dit le texte."),
    )

    assert from_exchange == manual
    assert len(list_flashcards()) == 1


def test_editing_a_card_moves_its_key_with_its_text(fresh_db):
    """La clé suit le texte : l'ancien recto/verso redevient libre, le nouveau
    est protégé, et une édition ne peut pas fabriquer un doublon."""
    import pytest

    from db.flashcards import update_flashcard
    from services.flashcards import create_flashcard, find_flashcard, list_flashcards

    card = create_flashcard(front="Q1", back="R1")
    other = create_flashcard(front="Q2", back="R2")

    update_flashcard(card, front="Q3")
    assert find_flashcard("Q3", "R1") == card
    assert find_flashcard("Q1", "R1") is None
    # Le nouveau texte est protégé comme s'il avait été créé ainsi.
    assert create_flashcard(front="q3", back="r1") == card
    assert len(list_flashcards()) == 2

    # Réécrire la carte à l'identique d'une autre est refusé.
    with pytest.raises(ValueError):
        update_flashcard(other, front="Q3", back="R1")
    assert find_flashcard("Q2", "R2") == other
