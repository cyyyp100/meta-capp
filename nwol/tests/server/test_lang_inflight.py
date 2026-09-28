# Flux hérité : une seule génération par exercice (K4, défaut n° 4).
#
# Quand l'apprenant arrivait sur l'exercice suivant avant la fin de son
# préchargement, une seconde génération identique partait en file derrière la
# première. Il attend désormais le résultat du préchargement.
import threading
import time


def _setup(client, monkeypatch, calls, gate):
    monkeypatch.setattr("services.lang.ENABLE_PREFETCH", True)
    monkeypatch.setattr("services.lang_sequencer.plan_lesson_async",
                        lambda state, level, language, phase, ok, err, model=None: ok({"theme": "Au café"}))

    def slow_content(language, session_type, profile, weak_points, ok, err, model=None, due_cards=None):
        calls.append(session_type)
        if len(calls) > 1:
            gate.wait(3)
        ok({"kind": "vocabulary", "render_kind": "vocabulary", "session_type": session_type,
            "items": [], "questions": []})

    monkeypatch.setattr("services.lang.generate_session_content_async", slow_content)
    client.post("/api/lang/placement/skip", json={"language": "italien"})


def test_exercise_requested_during_its_prefetch_is_generated_once(client, monkeypatch):
    calls: list[str] = []
    gate = threading.Event()
    _setup(client, monkeypatch, calls, gate)
    start = client.post("/api/lang/lesson/start", json={"language": "italien"}).json()
    lesson_id = start["lesson_id"]
    deadline = time.monotonic() + 3
    while len(calls) < 2 and time.monotonic() < deadline:  # le préchargement de l'exercice 1 est parti
        time.sleep(0.01)
    threading.Timer(0.3, gate.set).start()
    res = client.get(f"/api/lang/lesson/{lesson_id}/exercise/1").json()
    assert res["exercise"] and not res.get("error")
    assert len(calls) == 2, calls  # exercice 0 + UN seul exercice 1


def test_unscored_exercises_are_null_not_perfect(client, monkeypatch):
    """K1 : un exercice sans item noté ne compte pas pour 1.0."""
    calls: list[str] = []
    _setup(client, monkeypatch, calls, threading.Event())
    monkeypatch.setattr("services.lang.ENABLE_PREFETCH", False)
    lesson_id = client.post("/api/lang/lesson/start", json={"language": "italien"}).json()["lesson_id"]
    scores = [None] * 9 + [0.5]
    assert client.post(f"/api/lang/lesson/{lesson_id}/complete",
                       json={"exercise_scores": scores, "duration_s": 60}).json()["ok"]
    profile = client.get("/api/lang/profile", params={"language": "italien"}).json()
    assert profile["progress"]["avg_score"] == 50.0
    empty = client.post("/api/lang/lesson/start", json={"language": "italien"}).json()["lesson_id"]
    client.post(f"/api/lang/lesson/{empty}/complete", json={"exercise_scores": [None] * 10, "duration_s": 5})
    from db.lang_db import get_lang_lesson

    assert get_lang_lesson(empty)["score"] is None
