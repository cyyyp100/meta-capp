# Tests de la page Brainstorming (REST + WebSocket avec LLM mocké).
import queue

import pytest


@pytest.fixture(autouse=True)
def _no_question_left_in_flight():
    """La réservation « une question à la fois » vit en mémoire de processus :
    un test qui échoue en cours de réponse ne doit pas bloquer les suivants."""
    yield
    import services.brainstorm as svc

    svc._answering.clear()


# ── Fakes LLM (mêmes signatures callback que le code réel) ────────────────────

def _decide_no_search(history, user_message, on_success, on_error, model=None, **_):
    on_success({"search": False, "queries": []})


def _decide_with_search(history, user_message, on_success, on_error, model=None, **_):
    on_success({"search": True, "queries": ["vélo"]})


def _answer_fake(context, on_success, on_error, model=None):
    sources = context.get("sources") or []
    on_success(f"Réponse de test ({len(sources)} source(s)) : {context.get('user_message')}")


def _summarize_noop(previous_summary, new_messages, on_success, on_error, model=None):
    on_success("résumé de test")


# ── REST ──────────────────────────────────────────────────────────────────────

def test_brainstorm_crud(client):
    created = client.post("/api/brainstorming", json={"title": "Mon sujet"}).json()
    assert created["id"] >= 1
    assert created["title"] == "Mon sujet"

    listing = client.get("/api/brainstorming/discussions").json()
    assert any(d["id"] == created["id"] for d in listing)

    detail = client.get(f"/api/brainstorming/{created['id']}/messages").json()
    assert detail["title"] == "Mon sujet"
    assert detail["messages"] == []

    client.delete(f"/api/brainstorming/{created['id']}")
    assert client.get("/api/brainstorming/discussions").json() == []


def test_brainstorm_messages_404_on_unknown(client):
    assert client.get("/api/brainstorming/999/messages").status_code == 404


# ── WebSocket ─────────────────────────────────────────────────────────────────

def test_brainstorm_ws_answer_and_persist(client, monkeypatch):
    import services.brainstorm as svc

    monkeypatch.setattr(svc, "decide_brainstorm_search_async", _decide_no_search)
    monkeypatch.setattr(svc, "answer_brainstorm_async", _answer_fake)
    monkeypatch.setattr(svc, "summarize_brainstorm_async", _summarize_noop)

    did = client.post("/api/brainstorming", json={}).json()["id"]

    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json({"type": "ask", "question": "Idée sur le vélo"})
        assert ws.receive_json()["type"] == "loading"
        # 1er message d'une discussion vierge : son titre part avant la réponse.
        assert ws.receive_json() == {"type": "title", "title": "Idée sur le vélo"}
        answer = ws.receive_json()
        assert answer["type"] == "answer"
        assert "vélo" in answer["answer"]
        assert answer["sources"] == []

    detail = client.get(f"/api/brainstorming/{did}/messages").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    # Auto-titre depuis la 1re question (discussion créée sans titre).
    assert detail["title"].startswith("Idée sur le vélo")


def test_brainstorm_ws_runs_db_search(client, monkeypatch):
    import services.brainstorm as svc

    captured = {}

    def _spy_search(query, *a, **k):
        captured["query"] = query
        return [{"source_type": "highlight", "doc_title": "PDF", "page": 3, "snippet": "passage vélo"}]

    monkeypatch.setattr(svc, "decide_brainstorm_search_async", _decide_with_search)
    monkeypatch.setattr(svc, "answer_brainstorm_async", _answer_fake)
    monkeypatch.setattr(svc, "summarize_brainstorm_async", _summarize_noop)
    monkeypatch.setattr(svc.brainstorm_search, "search_user_db", _spy_search)

    did = client.post("/api/brainstorming", json={"title": "Vélo"}).json()["id"]

    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json({"type": "ask", "question": "Parle-moi de vélo"})
        events = []
        # loading -> scanning(on) -> scanning(off) -> answer (ordre exact non garanti
        # pour les scanning, mais answer arrive en dernier).
        while True:
            evt = ws.receive_json()
            events.append(evt)
            if evt["type"] == "answer":
                break

    types = [e["type"] for e in events]
    assert "loading" in types
    assert "scanning" in types
    assert captured["query"] == "vélo"
    answer = events[-1]
    assert answer["sources"] and answer["sources"][0]["source_type"] == "highlight"
    assert "1 source" in answer["answer"]


def test_brainstorm_question_is_bounded(client, monkeypatch):
    """S4 : une question démesurée est TRONQUÉE, pas refusée.

    Le WebSocket du lecteur borne ses entrées depuis toujours (`ReaderMessage`) ;
    celui du brainstorming ne le faisait pas, et la chaîne partait telle quelle
    dans un prompt. On tronque plutôt que de fermer le socket : une question trop
    longue reste une question, et fermer ferait perdre la discussion."""
    from server.routers import brainstorming as router
    from services import brainstorm as svc

    seen: dict = {}

    def _capture(discussion_id, question, on_answer, on_error, on_scanning, **_):
        seen["question"] = question
        on_answer({"answer": "ok", "sources": []})

    monkeypatch.setattr(svc, "handle_message", _capture)

    did = client.post("/api/brainstorming", json={"title": "Bornage"}).json()["id"]
    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json({"type": "ask", "question": "a" * 10_000})
        while ws.receive_json()["type"] != "answer":
            pass

    assert len(seen["question"]) == router._MAX_QUESTION_CHARS


def test_brainstorm_ignores_non_dict_message(client, monkeypatch):
    """Un message JSON qui n'est pas un objet ne doit pas faire tomber le socket.

    `msg.get(...)` sur une liste lève un AttributeError qui remontait jusqu'au
    gestionnaire d'exception du WebSocket et fermait le canal. Même chose pour
    une trame qui n'est pas du JSON du tout."""
    from services import brainstorm as svc

    asked: list = []

    def _answer(discussion_id, question, on_answer, on_error, on_scanning, **_):
        asked.append(question)
        on_answer({"answer": "ok", "sources": []})

    monkeypatch.setattr(svc, "handle_message", _answer)

    did = client.post("/api/brainstorming", json={"title": "Robuste"}).json()["id"]
    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json(["pas", "un", "objet"])   # ignoré
        ws.send_json({"type": "inconnu"})      # ignoré
        ws.send_text("{pas du json")           # ignoré
        # Une question qui n'est pas une chaîne n'est pas convertie en texte.
        ws.send_json({"type": "ask", "question": {"piège": 1}})
        # Le socket est toujours vivant : un `ask` valide obtient sa réponse.
        ws.send_json({"type": "ask", "question": "toujours là ?"})
        while ws.receive_json()["type"] != "answer":
            pass

    assert asked == ["toujours là ?"]


# ── Recherche en base : pertinence, diversité, rotation ──────────────────────
#
# Avant, chaque source rendait « les 3 premiers matchs dans l'ordre des id », le
# tout concaténé dans un ordre fixe : la réponse citait toujours les 3 surlignages
# et les 3 flashcards les plus récents, une Q&R ou un document n'apparaissaient
# jamais, et reposer la même question rendait la MÊME liste au caractère près.

def _seed_highlights(n: int, word: str = "photosynthese") -> int:
    from db.documents import upsert_document
    from db.reader_highlights import add_highlight

    doc_id = upsert_document(
        path="/tmp/bio.pdf", filename="bio.pdf", page_count=n + 1,
        engine="test", has_toc=False, subject="biologie",
    )
    for i in range(n):
        add_highlight(doc_id, page=i + 1, quote=f"Extrait {i} sur la {word}.", rects=[])
    return doc_id


def test_search_is_not_limited_to_the_newest_rows(client):
    """Un surlignage ancien doit pouvoir être cité s'il répond à la question."""
    from services.brainstorm_search import search_user_db

    _seed_highlights(80)
    seen: set[str] = set()
    for _ in range(40):
        seen.update(item["snippet"] for item in search_user_db("photosynthèse"))
    # Avant : exactement 3 extraits, toujours les mêmes (les 3 plus récents).
    assert len(seen) > 10


def test_search_spreads_across_source_types(client):
    """Plafond par type : une Q&R et un document ne sont plus affamés par les surlignages."""
    from db.flashcards import save_flashcard
    from db.questions import save_assistant_exchange
    from db.user import DEFAULT_USER_ID
    from services.brainstorm_search import search_user_db

    doc_id = _seed_highlights(30)
    for i in range(10):
        save_flashcard(DEFAULT_USER_ID, None, f"photosynthese {i} ?", "réponse", document_id=doc_id)
        save_assistant_exchange(doc_id, i + 1, f"photosynthese, comment ? {i}", "explication")

    types_seen: set[str] = set()
    for _ in range(20):
        types_seen.update(item["source_type"] for item in search_user_db("photosynthèse"))
    assert {"highlight", "flashcard", "qa"} <= types_seen

    for _ in range(20):
        counts: dict[str, int] = {}
        for item in search_user_db("photosynthèse"):
            counts[item["source_type"]] = counts.get(item["source_type"], 0) + 1
        assert max(counts.values()) <= 2, counts


def test_search_favours_the_most_relevant_without_locking_onto_it(client):
    """Deux termes trouvés pèsent bien plus qu'un seul, sans rendre le tirage figé.

    L'extrait qui touche TOUTE la requête est en concurrence avec 30 extraits qui
    n'en touchent que la moitié, pour 2 places. Un tirage neutre le sortirait dans
    ~6 % des tours (2/31) ; la pente de pertinence doit le hisser bien au-dessus.

    Mais l'assertion s'arrête là : exiger qu'il sorte à TOUS les tours reviendrait
    à réclamer le déterminisme que cette sélection existe justement pour casser.
    """
    from db.documents import upsert_document
    from db.reader_highlights import add_highlight
    from services.brainstorm_search import search_user_db

    doc_id = upsert_document(
        path="/tmp/bio2.pdf", filename="bio2.pdf", page_count=50,
        engine="test", has_toc=False, subject="biologie",
    )
    add_highlight(doc_id, page=1, quote="La photosynthese et la chlorophylle ensemble.", rects=[])
    for i in range(30):
        add_highlight(doc_id, page=i + 2, quote=f"Juste la photosynthese, note {i}.", rects=[])

    hits = 0
    for _ in range(100):
        snippets = [item["snippet"] for item in search_user_db("photosynthèse chlorophylle")]
        hits += any("chlorophylle" in s for s in snippets)
    assert hits > 20, f"le plus pertinent ne sort que {hits} fois sur 100 (hasard : ~6)"


def test_already_cited_sources_are_damped(client):
    """Une source déjà citée recule sans être exclue."""
    from services.brainstorm_search import search_user_db, source_key

    _seed_highlights(20)
    first = search_user_db("photosynthèse")
    assert first
    damp = {source_key(item) for item in first}

    repeats = 0
    for _ in range(30):
        again = search_user_db("photosynthèse", damp_keys=damp)
        repeats += sum(source_key(item) in damp for item in again)
    # Sans amortissement, les mêmes extraits reviendraient massivement.
    assert repeats < 30, f"{repeats} re-citations sur 30 tours"


def test_search_returns_nothing_without_usable_terms(client):
    from services.brainstorm_search import search_user_db

    _seed_highlights(5)
    assert search_user_db("le la les") == []
    assert search_user_db("") == []
    assert search_user_db("photosynthèse", limit=0) == []


# ── Titre immédiat ────────────────────────────────────────────────────────────

def test_title_is_pushed_before_the_answer(client, monkeypatch):
    """Le titre tiré du 1er message part AVANT la réponse : la liste le montre dès
    l'envoi, au lieu de rester sur « Nouvelle discussion » toute la génération."""
    import services.brainstorm as svc

    monkeypatch.setattr(svc, "decide_brainstorm_search_async", _decide_no_search)
    monkeypatch.setattr(svc, "answer_brainstorm_async", _answer_fake)
    monkeypatch.setattr(svc, "summarize_brainstorm_async", _summarize_noop)

    did = client.post("/api/brainstorming", json={}).json()["id"]
    question = "Comment   relier la photosynthèse et la respiration cellulaire dans un même schéma global ?"
    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json({"type": "ask", "question": question})
        types = []
        title = None
        while True:
            evt = ws.receive_json()
            types.append(evt["type"])
            if evt["type"] == "title":
                title = evt["title"]
            if evt["type"] == "answer":
                break
        # 2e message : la discussion a déjà un nom, pas de nouvel événement.
        ws.send_json({"type": "ask", "question": "Et ensuite ?"})
        second = []
        while True:
            evt = ws.receive_json()
            second.append(evt["type"])
            if evt["type"] == "answer":
                break

    assert types.index("title") < types.index("answer")
    assert "title" not in second
    # Espaces compactés, coupe sur une frontière de mot, jamais au-delà de 60.
    assert title.endswith("…") and len(title) <= 60
    assert "  " not in title
    assert question.replace("   ", " ").startswith(title[:-1])
    listing = client.get("/api/brainstorming/discussions").json()
    assert listing[0]["title"] == title


def test_title_from_message_cuts_on_a_word():
    from services.brainstorm import _title_from_message

    assert _title_from_message("  Idée   courte ") == "Idée courte"
    long = "mot " * 30
    title = _title_from_message(long)
    assert title.endswith("…") and not title[:-1].endswith(" ")
    assert len(title) <= 60
    # Un seul mot démesuré est coupé plutôt que de rendre un titre vide.
    assert len(_title_from_message("x" * 200)) == 60


# ── Épinglage ─────────────────────────────────────────────────────────────────

def test_pin_limit_and_order(client):
    from config.settings import BRAINSTORM_MAX_PINNED

    ids = [
        client.post("/api/brainstorming", json={"title": f"D{i}"}).json()["id"]
        for i in range(BRAINSTORM_MAX_PINNED + 2)
    ]
    for did in ids[:BRAINSTORM_MAX_PINNED]:
        res = client.post(f"/api/brainstorming/{did}/pin", json={"pinned": True})
        assert res.status_code == 200 and res.json()["pinned_at"]

    over = client.post(f"/api/brainstorming/{ids[-1]}/pin", json={"pinned": True})
    assert over.status_code == 400
    assert str(BRAINSTORM_MAX_PINNED) in over.json()["detail"]
    # Ré-épingler une épinglée n'est pas un dépassement.
    assert client.post(f"/api/brainstorming/{ids[0]}/pin", json={"pinned": True}).status_code == 200

    # Les épinglées sont en tête, même si une autre discussion est plus récente.
    listing = client.get("/api/brainstorming/discussions").json()
    head = {d["id"] for d in listing[:BRAINSTORM_MAX_PINNED]}
    assert head == set(ids[:BRAINSTORM_MAX_PINNED])
    assert all(d["pinned_at"] is None for d in listing[BRAINSTORM_MAX_PINNED:])

    # Désépingler libère une place.
    client.post(f"/api/brainstorming/{ids[0]}/pin", json={"pinned": False})
    assert client.post(f"/api/brainstorming/{ids[-1]}/pin", json={"pinned": True}).status_code == 200


def test_pin_unknown_discussion_is_400(client):
    assert client.post("/api/brainstorming/999/pin", json={"pinned": True}).status_code == 400


# ── Lien à un dossier ─────────────────────────────────────────────────────────

def _folder(client, name: str, parent_id: int | None = None) -> int:
    return client.post("/api/library/folders", json={"name": name, "parent_id": parent_id}).json()["id"]


def test_link_folder_and_folder_deletion(client):
    folder_id = _folder(client, "Biologie")
    created = client.post("/api/brainstorming", json={"title": "Bio", "folder_id": folder_id}).json()
    assert created["folder_id"] == folder_id and created["folder_name"] == "Biologie"

    assert client.post("/api/brainstorming", json={"folder_id": 999}).status_code == 400
    assert client.post(f"/api/brainstorming/{created['id']}/folder", json={"folder_id": 999}).status_code == 400

    unlinked = client.post(f"/api/brainstorming/{created['id']}/folder", json={"folder_id": None}).json()
    assert unlinked["folder_id"] is None
    client.post(f"/api/brainstorming/{created['id']}/folder", json={"folder_id": folder_id})

    # Supprimer le dossier délie la discussion (ON DELETE SET NULL), sans la supprimer.
    client.delete(f"/api/library/folders/{folder_id}")
    detail = client.get(f"/api/brainstorming/{created['id']}/messages").json()
    assert detail["folder_id"] is None


def _seed_doc_with_material(path: str, word: str) -> int:
    """Un document avec surlignage, flashcard, Q&R et erreur qui parlent de ``word``."""
    from db.answers import save_answer
    from db.documents import upsert_document
    from db.flashcards import save_flashcard
    from db.questions import save_assistant_exchange, save_question
    from db.reader_highlights import add_highlight
    from db.user import DEFAULT_USER_ID

    doc_id = upsert_document(
        path=path, filename=path.rsplit("/", 1)[-1], page_count=10,
        engine="test", has_toc=False, subject="biologie",
    )
    add_highlight(doc_id, page=1, quote=f"Surlignage sur la {word}.", rects=[])
    save_flashcard(DEFAULT_USER_ID, None, f"{word} ?", "réponse", document_id=doc_id)
    save_assistant_exchange(doc_id, 2, f"{word}, comment ?", "explication")
    qid = save_question(
        doc_id, "page", "Page 3", 3, 3,
        {"question": f"Définis la {word}.", "answer": "la bonne définition"},
    )
    save_answer(qid, DEFAULT_USER_ID, "une confusion", verdict="incorrect")
    return doc_id


def test_search_is_scoped_to_the_folder_subtree(client):
    from db.folders import descendant_ids, set_document_folder
    from services.brainstorm_search import search_user_db

    parent = _folder(client, "Cours")
    child = _folder(client, "Chapitre 1", parent)
    inside = _seed_doc_with_material("/tmp/in.pdf", "photosynthese")
    nested = _seed_doc_with_material("/tmp/nested.pdf", "photosynthese")
    outside = _seed_doc_with_material("/tmp/out.pdf", "photosynthese")
    set_document_folder(inside, parent)
    set_document_folder(nested, child)

    scope = descendant_ids(parent)
    seen_docs: set = set()
    seen_types: set = set()
    for _ in range(40):
        for item in search_user_db("photosynthèse", limit=10, folder_ids=scope):
            seen_docs.add(item["doc_id"])
            seen_types.add(item["source_type"])
    assert seen_docs == {inside, nested}, "une source hors dossier a fui"
    assert outside not in seen_docs
    assert {"highlight", "flashcard", "qa", "mistake"} <= seen_types

    # Sans dossier : toute la base.
    unscoped = set()
    for _ in range(40):
        unscoped.update(item["doc_id"] for item in search_user_db("photosynthèse", limit=10))
    assert outside in unscoped

    # Dossier vide : aucun document, donc rien — jamais « toute la base ».
    empty = _folder(client, "Vide")
    assert search_user_db("photosynthèse", folder_ids=descendant_ids(empty)) == []
    assert search_user_db("photosynthèse", folder_ids=set()) == []


def test_mistakes_only_cover_wrong_answers(client):
    from db.answers import save_answer
    from db.documents import upsert_document
    from db.questions import save_question
    from db.user import DEFAULT_USER_ID
    from services.brainstorm_search import search_user_db

    doc_id = upsert_document(
        path="/tmp/chimie.pdf", filename="chimie.pdf", page_count=5,
        engine="test", has_toc=False, subject="chimie",
    )
    ok = save_question(doc_id, "page", "Page 1", 1, 1, {"question": "Qu'est-ce qu'un isotope ?", "answer": "x"})
    ko = save_question(doc_id, "page", "Page 2", 2, 2, {"question": "Qu'est-ce qu'un isotope radioactif ?", "answer": "y"})
    save_answer(ok, DEFAULT_USER_ID, "bonne réponse", verdict="correct")
    save_answer(ko, DEFAULT_USER_ID, "mauvaise réponse", verdict="incorrect")

    snippets = [
        item["snippet"]
        for _ in range(20)
        for item in search_user_db("isotope")
        if item["source_type"] == "mistake"
    ]
    assert snippets and all("radioactif" in s and "mauvaise réponse" in s for s in snippets)


def test_linked_discussion_searches_only_its_folder(client, monkeypatch):
    """Bout en bout : la discussion liée transmet le sous-arbre à la recherche et
    nomme le dossier dans les deux prompts."""
    import services.brainstorm as svc
    from db.folders import set_document_folder

    parent = _folder(client, "Cours")
    child = _folder(client, "Chapitre 1", parent)
    doc_id = _seed_doc_with_material("/tmp/vélo.pdf", "vélo")
    set_document_folder(doc_id, child)

    captured: dict = {}

    def _decide(history, user_message, on_success, on_error, model=None, scope=None):
        captured["decide_scope"] = scope
        on_success({"search": True, "queries": ["vélo"]})

    def _answer(context, on_success, on_error, model=None):
        captured["answer_scope"] = context.get("scope")
        on_success("ok")

    def _spy_search(query, *a, folder_ids=None, **k):
        captured["folder_ids"] = folder_ids
        return []

    monkeypatch.setattr(svc, "decide_brainstorm_search_async", _decide)
    monkeypatch.setattr(svc, "answer_brainstorm_async", _answer)
    monkeypatch.setattr(svc, "summarize_brainstorm_async", _summarize_noop)
    monkeypatch.setattr(svc.brainstorm_search, "search_user_db", _spy_search)

    did = client.post("/api/brainstorming", json={"title": "Vélo", "folder_id": parent}).json()["id"]
    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json({"type": "ask", "question": "Parle-moi de vélo"})
        while ws.receive_json()["type"] != "answer":
            pass

    assert captured["folder_ids"] == {parent, child}
    assert captured["decide_scope"]["name"] == "Cours"
    assert captured["answer_scope"]["titles"] == ["vélo.pdf"]


def test_scope_block_names_the_folder_in_prompts():
    from llm.prompts import build_brainstorm_answer_prompt, build_brainstorm_search_decide_prompt

    scope = {"folder_ids": {1}, "name": "Cours", "titles": ["a.pdf", "b.pdf"], "total": 5}
    decide = build_brainstorm_search_decide_prompt([], "question", scope)
    answer = build_brainstorm_answer_prompt("", [], "question", [], scope)
    for prompt in (decide, answer):
        assert "Cours" in prompt and "a.pdf, b.pdf (+3)" in prompt
    assert "Cours" not in build_brainstorm_answer_prompt("", [], "question", [])


# ── Garde-fous ────────────────────────────────────────────────────────────────

def _ask_until_answer(client, did: int, question: str) -> None:
    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json({"type": "ask", "question": question})
        while ws.receive_json()["type"] != "answer":
            pass


def test_new_discussion_reopens_the_blank_one(client, monkeypatch):
    """Dix clics sur « Nouvelle discussion » faisaient dix discussions vides.
    Tant que la page blanche n'a pas servi, c'est elle qui revient."""
    import services.brainstorm as svc

    monkeypatch.setattr(svc, "decide_brainstorm_search_async", _decide_no_search)
    monkeypatch.setattr(svc, "answer_brainstorm_async", _answer_fake)
    monkeypatch.setattr(svc, "summarize_brainstorm_async", _summarize_noop)

    first = client.post("/api/brainstorming", json={}).json()["id"]
    for _ in range(5):
        assert client.post("/api/brainstorming", json={}).json()["id"] == first
    # Le titre par défaut, envoyé tel quel, ne contourne pas la règle.
    assert client.post("/api/brainstorming", json={"title": "Nouvelle discussion"}).json()["id"] == first
    assert len(client.get("/api/brainstorming/discussions").json()) == 1

    # Rouverte avec un dossier : elle y est liée. Sans dossier : son lien reste.
    folder_id = _folder(client, "Biologie")
    reopened = client.post("/api/brainstorming", json={"folder_id": folder_id}).json()
    assert reopened["id"] == first and reopened["folder_id"] == folder_id
    assert client.post("/api/brainstorming", json={}).json()["folder_id"] == folder_id

    # Une fois qu'elle a servi, la suivante est bien une nouvelle discussion.
    _ask_until_answer(client, first, "Une idée")
    second = client.post("/api/brainstorming", json={}).json()["id"]
    assert second != first
    # Un vrai titre crée toujours, même à côté d'une page blanche.
    named = client.post("/api/brainstorming", json={"title": "Mon sujet"}).json()["id"]
    assert named not in (first, second)


def test_create_title_is_bounded(client):
    from db.brainstorm import TITLE_MAX_CHARS

    too_long = {"title": "x" * (TITLE_MAX_CHARS + 1)}
    assert client.post("/api/brainstorming", json=too_long).status_code == 422


def test_migration_v34_keeps_a_single_blank_discussion(client):
    """Les pages blanches déjà empilées sont résorbées : la plus récente reste,
    ainsi que celles que l'utilisateur a épinglées ou liées à un dossier."""
    from db import brainstorm as store
    from db import get_connection
    from db.migrations import _migrate_to_v34

    folder_id = _folder(client, "Maths")
    pinned = store.create_discussion("")
    store.pin_discussion(pinned, 5)
    linked = store.create_discussion("", folder_id=folder_id)
    used = store.create_discussion("")
    store.add_message(used, "user", "bonjour")
    named = store.create_discussion("Mon sujet")
    blanks = [store.create_discussion("") for _ in range(4)]

    _migrate_to_v34(get_connection())

    remaining = {d["id"] for d in store.list_discussions()}
    assert remaining == {pinned, linked, used, named, blanks[-1]}


def test_one_question_at_a_time_per_discussion(client, monkeypatch):
    """Tant que Gemma répond, une seconde question dans la MÊME discussion est
    refusée sans rien persister : deux questions croisées entrelaçaient leurs
    messages et chaque réponse ignorait l'autre."""
    import services.brainstorm as svc
    from i18n import t

    # La décision part d'un thread de l'executor : on l'attend, on ne la suppose pas là.
    pending: queue.Queue = queue.Queue()

    def _decide_later(history, user_message, on_success, on_error, model=None, **_):
        pending.put(on_success)

    monkeypatch.setattr(svc, "decide_brainstorm_search_async", _decide_later)
    monkeypatch.setattr(svc, "answer_brainstorm_async", _answer_fake)
    monkeypatch.setattr(svc, "summarize_brainstorm_async", _summarize_noop)

    did = client.post("/api/brainstorming", json={"title": "Occupée"}).json()["id"]
    with client.websocket_connect(f"/api/brainstorming/{did}/stream") as ws:
        ws.send_json({"type": "ask", "question": "première"})
        assert ws.receive_json()["type"] == "loading"
        ws.send_json({"type": "ask", "question": "seconde"})
        assert ws.receive_json()["type"] == "loading"
        assert ws.receive_json() == {"type": "error", "message": t("brainstorm.busy")}
        # Le détail le dit : un client qui rouvre la discussion attend la réponse.
        assert client.get(f"/api/brainstorming/{did}/messages").json()["answering"] is True

        pending.get(timeout=5)({"search": False, "queries": []})
        answer = ws.receive_json()
        assert answer["type"] == "answer" and "première" in answer["answer"]

        # Libérée : la question suivante passe.
        ws.send_json({"type": "ask", "question": "troisième"})
        assert ws.receive_json()["type"] == "loading"
        pending.get(timeout=5)({"search": False, "queries": []})
        assert ws.receive_json()["type"] == "answer"

    detail = client.get(f"/api/brainstorming/{did}/messages").json()
    assert detail["answering"] is False
    assert [m["content"] for m in detail["messages"] if m["role"] == "user"] == ["première", "troisième"]


def test_failure_before_queueing_releases_the_discussion(client, monkeypatch):
    """Une panne avant la mise en file répond une erreur et libère la discussion,
    au lieu de la laisser réservée — donc muette — jusqu'au redémarrage."""
    import services.brainstorm as svc
    from i18n import t

    def _boom(*_a, **_k):
        raise RuntimeError("file LLM cassée")

    monkeypatch.setattr(svc, "decide_brainstorm_search_async", _boom)

    did = client.post("/api/brainstorming", json={"title": "Panne"}).json()["id"]
    answers: list = []
    errors: list = []
    svc.handle_message(did, "question", answers.append, errors.append)

    assert answers == [] and errors == [t("brainstorm.failed")]
    assert not svc.is_answering(did)


def test_ws_on_unknown_discussion_is_closed(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/api/brainstorming/999/stream") as ws:
            ws.receive_json()
    assert closed.value.code == 4404
