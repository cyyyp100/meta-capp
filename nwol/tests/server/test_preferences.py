# Langue de l'interface -> langue des prompts LLM (§ A3).
#
# Avant l'unification, `i18n.set_lang` n'était appelé que par l'UI Tk : basculer
# le frontend en anglais donnait une UI anglaise et un Gemma francophone. Ces
# tests verrouillent le fait que la bascule atteint bien le backend.
import pytest


@pytest.fixture(autouse=True)
def _restore_lang():
    import i18n

    before = i18n.current_lang()
    yield
    i18n.set_lang(before)


def test_lang_defaults_to_french(client):
    body = client.get("/api/preferences/lang").json()
    assert body["lang"] == "fr"
    assert set(body["supported"]) == {"fr", "en"}


def test_post_lang_switches_backend_and_prompts(client):
    import i18n

    assert client.post("/api/preferences/lang", json={"lang": "en"}).json()["lang"] == "en"
    # Le module i18n du backend suit -> les branches anglaises de llm/prompts.py
    # deviennent atteignables (elles testent current_lang()).
    assert i18n.current_lang() == "en"
    assert i18n.t("home.subtitle") == i18n.STRINGS["en"]["home.subtitle"]
    assert i18n.t("home.subtitle") != i18n.STRINGS["fr"]["home.subtitle"]

    assert client.post("/api/preferences/lang", json={"lang": "fr"}).json()["lang"] == "fr"
    assert i18n.current_lang() == "fr"


def test_post_lang_rejects_unknown_language(client):
    import i18n

    assert client.post("/api/preferences/lang", json={"lang": "kl"}).status_code == 400
    assert i18n.current_lang() == "fr"


def test_lang_choice_is_persisted_for_next_start(client):
    from db.user import DEFAULT_USER_ID, get_user_lang
    from server.routers.preferences import apply_stored_lang
    import i18n

    client.post("/api/preferences/lang", json={"lang": "en"})
    assert get_user_lang(DEFAULT_USER_ID) == "en"

    # Simule un redémarrage du serveur : le lifespan restaure la langue stockée.
    i18n.set_lang("fr")
    apply_stored_lang()
    assert i18n.current_lang() == "en"
