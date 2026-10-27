# Routes des propositions de la relecture hebdomadaire (services/flashcard_check).


def _reviewer(fixes: dict[str, dict]):
    """Relecteur factice : corrige les cartes dont le recto est dans `fixes`."""

    def checker(context, ok, err):
        fix = fixes.get(context["front"])
        ok({"verdict": "fix", **fix} if fix else {"verdict": "ok", **context, "reason": ""})

    return checker


def test_routes_list_accept_and_dismiss(client, no_startup_flashcard_check, monkeypatch):
    from services import flashcard_check

    monkeypatch.setattr(flashcard_check, "background_suspended", lambda task: False)
    first = client.post("/api/flashcards", json={"front": "Que vaut 2 + 2 ?", "back": "5"}).json()["id"]
    second = client.post("/api/flashcards", json={"front": "Que vaut 3 + 3 ?", "back": "7"}).json()["id"]
    no_startup_flashcard_check(checker=_reviewer({
        "Que vaut 2 + 2 ?": {"front": "Que vaut 2 + 2 ?", "back": "4", "reason": "Faux."},
        "Que vaut 3 + 3 ?": {"front": "Que vaut 3 + 3 ?", "back": "6", "reason": "Faux."},
    }))

    assert {s["card_id"] for s in client.get("/api/flashcards/suggestions").json()} == {first, second}
    assert client.post(f"/api/flashcards/{first}/suggestion/accept").json()["back"] == "4"
    assert client.post(f"/api/flashcards/{second}/suggestion/dismiss").json() == {"ok": True}
    assert client.get("/api/flashcards/suggestions").json() == []
    assert client.post(f"/api/flashcards/{first}/suggestion/accept").status_code == 404
