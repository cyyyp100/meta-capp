# Tests des séances Assimil (10 exercices, arc 4 temps), du test de niveau et de
# la génération automatique de flashcards de vocabulaire. Les appels LLM sont
# remplacés par des fakes (signature callback ok/err) — aucun Ollama requis.


# ── Fakes LLM ─────────────────────────────────────────────────────────────────

def _fake_plan(state, level, language, phase, ok, err, model=None):
    ok({"theme": "Au café", "intro": ""})


def _fake_vocab_content(language, session_type, profile, weak_points, ok, err, model=None, due_cards=None):
    # Recto attendu = français (translation), verso = langue cible (word).
    ok({
        "kind": "vocabulary",
        "render_kind": "vocabulary",
        "session_type": session_type,
        "items": [{
            "word": "soon", "translation": "bientôt",
            "example_target": "see you soon", "example_translation": "à bientôt",
        }],
        "questions": [],
    })


def _fake_placement_test(language, script, ok, err, model=None):
    ok({"items": [
        {"id": 1, "level": "A1", "skill": "comprehension", "format": "qcm",
         "question": "q1", "choices": ["A: x", "B: y"], "correct": "A"},
        {"id": 2, "level": "B1", "skill": "comprehension", "format": "qcm",
         "question": "q2", "choices": ["A: x", "B: y"], "correct": "B"},
    ]})


def _fake_placement_eval(language, summary, ok, err, model=None):
    ok({"cefr": "A2", "can_read_script": True, "comment": "bon début"})


def _patch_lesson_llm(monkeypatch):
    monkeypatch.setattr("services.lang.ENABLE_PREFETCH", False)
    monkeypatch.setattr("services.lang_sequencer.plan_lesson_async", _fake_plan)
    monkeypatch.setattr("services.lang.generate_session_content_async", _fake_vocab_content)


# ── Gate test de niveau ───────────────────────────────────────────────────────

def test_start_lesson_requires_placement(client):
    body = client.post("/api/lang/lesson/start", json={"language": "anglais"}).json()
    assert body["needs_placement"] is True
    assert body["script"] == "latin"


def test_placement_skip_sets_beginner_entry(client):
    body = client.post("/api/lang/placement/skip", json={"language": "anglais"}).json()
    assert body["ok"] is True and body["level"] == "A1" and body["phase"] == "passive"
    # placement_done est posé : start_lesson ne redemande plus le test.
    prof = client.get("/api/lang/profile", params={"language": "anglais"}).json()["profile"]
    assert prof["placement_done"] == 1


def test_placement_submit_estimates_level(client, monkeypatch):
    monkeypatch.setattr("services.lang.generate_placement_test_async", _fake_placement_test)
    monkeypatch.setattr("services.lang.evaluate_placement_async", _fake_placement_eval)

    items = client.post("/api/lang/placement/start", json={"language": "anglais"}).json()["items"]
    assert len(items) == 2
    assert "correct" not in items[0]  # les réponses ne fuitent pas vers le client

    res = client.post(
        "/api/lang/placement/submit",
        json={"language": "anglais", "answers": {"1": "A", "2": "B"}},
    ).json()
    assert res["ok"] is True and res["level"] == "A2" and res["phase"] == "passive"
    prof = client.get("/api/lang/profile", params={"language": "anglais"}).json()["profile"]
    assert prof["level"] == "A2"


# ── Phase écriture (script non-latin) ─────────────────────────────────────────

def test_russian_starts_in_writing_phase(client):
    client.post("/api/lang/placement/skip", json={"language": "russe"}).json()
    body = client.get("/api/lang/profile", params={"language": "russe"}).json()
    assert body["script"] == "cyrillic"
    assert body["profile"]["phase"] == "writing"


def test_writing_phase_plan_uses_script_types(client):
    from db.lang_db import get_or_create_lang_profile, update_lang_profile
    from services.lang_sequencer import plan_lesson

    prof = get_or_create_lang_profile(1, "russe")
    update_lang_profile(prof["id"], phase="writing", touch_last_session=False)
    prof = get_or_create_lang_profile(1, "russe")
    plan = plan_lesson(prof)  # russe + writing : pas d'appel LLM (thème déterministe)
    assert len(plan["slots"]) == 10
    kinds = {s["render_kind"] for s in plan["slots"]}
    assert kinds <= {"writing", "dictation", "revision"}
    assert plan["slots"][0]["temps"] == "ancrage"
    assert plan["slots"][-1]["temps"] == "cloture"


# ── Séance complète + flashcards de vocabulaire ───────────────────────────────

def test_full_lesson_flow_and_vocab_flashcards(client, monkeypatch):
    _patch_lesson_llm(monkeypatch)
    client.post("/api/lang/placement/skip", json={"language": "anglais"})

    start = client.post("/api/lang/lesson/start", json={"language": "anglais"}).json()
    lesson_id = start["lesson_id"]
    assert start["index"] == 0 and start["exercise"]["kind"] == "vocabulary"
    assert len(start["plan"]) == 10
    assert [s["temps"] for s in start["plan"]][:1] == ["ancrage"]

    # Parcourt les 9 exercices restants (génération JIT).
    for i in range(1, 10):
        ex = client.get(f"/api/lang/lesson/{lesson_id}/exercise/{i}").json()
        assert ex["index"] == i and ex["exercise"]["kind"] == "vocabulary"

    # Clôture : score + traçage des 10 exercices au grain compétence.
    done = client.post(
        f"/api/lang/lesson/{lesson_id}/complete",
        json={"exercise_scores": [1.0] * 10, "duration_s": 600},
    ).json()
    assert done["ok"] is True and done["total_lessons"] == 1

    from db import get_connection
    n_ex = get_connection().execute(
        "SELECT COUNT(*) AS n FROM lang_sessions WHERE lesson_id=?", (lesson_id,)
    ).fetchone()["n"]
    assert n_ex == 10

    # Flashcards : recto = mot connu + langue cible (« bientôt en anglais »),
    # verso = langue cible, dédupliquées (1 carte).
    rows = get_connection().execute(
        "SELECT front, back, source FROM flashcards WHERE language='anglais'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["front"] == "bientôt en anglais" and rows[0]["back"] == "soon"
    assert rows[0]["source"] == "lang_vocab"


# ── Signal de difficulté continue ─────────────────────────────────────────────

def test_difficulty_target_derives_from_history(client):
    from db.flashcards import save_flashcard
    from db.lang_db import get_or_create_lang_profile
    from services.lang_sequencer import compute_difficulty_target

    prof = get_or_create_lang_profile(1, "anglais")  # phase passive, vierge
    # Plancher passif (2) + 0 vocab + perf neutre (0) = 2.
    assert compute_difficulty_target(prof, prof["id"]) == 2

    # 40 cartes -> vocab_score min(40/20,5)=2 -> 2+2+0 = 4.
    for i in range(40):
        save_flashcard(1, None, f"fr{i}", f"en{i}", language="anglais")
    assert compute_difficulty_target(prof, prof["id"]) == 4

    # Garde-fou anti yo-yo : jamais plus de ±1 vs la séance précédente.
    assert compute_difficulty_target(prof, prof["id"], previous_difficulty=2) == 3
    assert compute_difficulty_target(prof, prof["id"], previous_difficulty=8) == 7


def test_start_lesson_exposes_difficulty(client, monkeypatch):
    _patch_lesson_llm(monkeypatch)
    client.post("/api/lang/placement/skip", json={"language": "anglais"})
    start = client.post("/api/lang/lesson/start", json={"language": "anglais"}).json()
    # Profil passif vierge : plancher de difficulté = 2, propagé au plan + à l'en-tête.
    assert start["difficulty_target"] == 2


def test_lesson_progress_counts_completed_lessons(client, monkeypatch):
    _patch_lesson_llm(monkeypatch)
    client.post("/api/lang/placement/skip", json={"language": "anglais"})
    start = client.post("/api/lang/lesson/start", json={"language": "anglais"}).json()
    client.post(
        f"/api/lang/lesson/{start['lesson_id']}/complete",
        json={"exercise_scores": [0.8] * 10, "duration_s": 300},
    )
    progress = client.get("/api/lang/profile", params={"language": "anglais"}).json()["progress"]
    assert progress["total_lessons"] == 1
    assert progress["avg_score"] == 80.0


# ── Pont SR → séance (plan1, Axe 1) ───────────────────────────────────────────

def _make_due_card(user_id, language, front, back):
    """Crée une flashcard de langue et force son échéance dans le passé (carte due)."""
    from db import get_connection
    from db.flashcards import save_flashcard
    cid = save_flashcard(user_id, None, front, back, language=language)
    with get_connection() as conn:
        conn.execute("UPDATE flashcards SET due_at=datetime('now','-2 day') WHERE id=?", (cid,))
    return cid


def test_due_flashcards_for_language_filters_due_and_language(client):
    from db.flashcards import save_flashcard
    from db.lang_db import get_due_flashcards_for_language, get_or_create_lang_profile

    prof = get_or_create_lang_profile(1, "anglais")
    cid = _make_due_card(1, "anglais", "bientôt", "soon")
    save_flashcard(1, None, "demain", "tomorrow", language="anglais")   # pas encore due (+1j)
    _make_due_card(1, "espagnol", "hola", "bonjour")                     # autre langue

    due = get_due_flashcards_for_language(prof["id"], "anglais", limit=8)
    assert [c["id"] for c in due] == [cid]
    assert due[0]["front"] == "bientôt" and due[0]["back"] == "soon"


def test_find_lang_flashcard_id_accent_folded(client):
    from db.lang_db import find_lang_flashcard_id, get_or_create_lang_profile

    prof = get_or_create_lang_profile(1, "anglais")
    cid = _make_due_card(1, "anglais", "bientôt", "soon")
    # Retrouvée par recto OU verso, insensible à la casse/accents.
    assert find_lang_flashcard_id(prof["id"], "anglais", "BIENTOT") == cid
    assert find_lang_flashcard_id(prof["id"], "anglais", "soon") == cid
    assert find_lang_flashcard_id(prof["id"], "anglais", "introuvable") is None


def test_plan_lesson_anchors_revision_on_due_cards_without_errors(client, monkeypatch):
    monkeypatch.setattr("services.lang_sequencer.plan_lesson_async", _fake_plan)
    from db.lang_db import get_or_create_lang_profile
    from services.lang_sequencer import plan_lesson

    prof = get_or_create_lang_profile(1, "anglais")  # phase passive, aucune erreur
    _make_due_card(1, "anglais", "bientôt", "soon")  # une carte due, zéro weak point

    plan = plan_lesson(prof)
    slots = plan["slots"]
    # Ancrage (0) et clôture (9) basculent sur la révision grâce aux cartes dues.
    assert slots[0]["exercise_type"] == "revision_adaptative"
    assert slots[9]["exercise_type"] == "revision_adaptative"


def test_deterministic_revision_falls_back_to_due_cards_without_llm(client):
    """Filet Axe 1 : sans LLM, la révision présente quand même les cartes dues."""
    from services.lang import _deterministic_revision_from_cards

    due = [{"id": 7, "front": "bientôt", "back": "soon"}, {"id": 8, "front": "", "back": "x"}]
    content = _deterministic_revision_from_cards(due, "revision_adaptative")
    assert content["kind"] == "revision"
    # La carte sans recto est écartée ; la valide garde son card_id pour le bouclage.
    assert len(content["exercises"]) == 1
    ex = content["exercises"][0]
    assert ex["prompt_fr"] == "bientôt" and ex["expected"] == "soon" and ex["card_id"] == 7


def test_sr_review_endpoint_reschedules_card(client):
    from db.lang_db import get_due_flashcards_for_language, get_or_create_lang_profile

    prof = get_or_create_lang_profile(1, "anglais")
    cid = _make_due_card(1, "anglais", "bientôt", "soon")
    assert len(get_due_flashcards_for_language(prof["id"], "anglais")) == 1

    # Révision réussie en séance → l'échéance est repoussée → carte plus due.
    resp = client.post("/api/lang/sr-review", json={
        "language": "anglais", "verdict": "correct", "card_id": cid,
    }).json()
    assert resp["ok"] is True and resp["matched"] is True
    assert get_due_flashcards_for_language(prof["id"], "anglais") == []


def test_sr_review_endpoint_matches_by_word(client):
    prof_word = "soon"
    cid = _make_due_card(1, "anglais", "bientôt", "soon")
    resp = client.post("/api/lang/sr-review", json={
        "language": "anglais", "verdict": "correct", "word": prof_word,
    }).json()
    assert resp["matched"] is True and resp.get("card_id") == cid
