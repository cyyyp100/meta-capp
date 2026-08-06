def test_lang_lesson(client, monkeypatch):
    from services import lang

    monkeypatch.setattr(
        lang, "generate_lang_curriculum_async",
        lambda language, ok, err: ok({"lessons": [{"lesson_n": 1, "theme": "Salutations", "vocabulary": [], "level": "A1"}]}),
    )
    monkeypatch.setattr(
        lang, "generate_lang_lesson_async",
        lambda language, n, row, ok, err: ok({
            "dialogue": [{"speaker": "A", "target": "Hello", "phonetic": "", "translation": "Bonjour"}],
            "notes": {"grammar": "g"},
            "vocabulary": [{"word": "hello", "translation": "bonjour", "example": ""}],
        }),
    )

    body = client.post("/api/lang/lesson", json={"language": "anglais"}).json()
    assert body["lesson_n"] == 1
    assert body["theme"] == "Salutations"
    assert body["dialogue"][0]["target"] == "Hello"
    assert body["vocabulary"][0]["word"] == "hello"


def test_flashcards_due_endpoint(client):
    # Endpoint fonctionnel ; une carte fraîche n'est pas encore due (due_at = +1j).
    resp = client.get("/api/flashcards/due")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
