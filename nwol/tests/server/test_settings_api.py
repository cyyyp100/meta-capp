"""Réglages d'application : `app_settings` a enfin du code (§ B2).

La table existait depuis la v25 et personne ne la lisait. Ces tests verrouillent
ce qui justifie de l'utiliser plutôt que le `localStorage` du webview : les
réglages vivent dans le fichier `.db`, donc dans la sauvegarde de l'utilisateur.
"""
from __future__ import annotations

import pytest


def test_defaults_are_served_for_a_fresh_database(client):
    body = client.get("/api/preferences").json()
    assert body["preferences"]["theme"] == "light"
    # Le seul appel sortant de l'app est coupé par défaut, et ce défaut est
    # une promesse produit, pas un détail d'implémentation.
    assert body["preferences"]["updates_check"] == "false"
    assert body["preferences"]["tour_done"] == "false"
    assert "system" in body["choices"]["theme"]


def test_patch_is_partial_and_persisted(client):
    client.post("/api/preferences", json={"theme": "system"})
    body = client.get("/api/preferences").json()
    assert body["preferences"]["theme"] == "system"
    # Les autres réglages n'ont pas bougé : c'est un patch, pas un remplacement.
    assert body["preferences"]["density"] == "comfortable"

    from db.app_settings import get_setting

    assert get_setting("theme") == "system"


@pytest.mark.parametrize("patch", [
    {"theme": "chartreuse"},
    {"reglage_inexistant": "1"},
    {"updates_check": "peut-être"},
])
def test_unknown_keys_and_values_are_refused(client, patch):
    """Un réglage refusé doit être une erreur visible, pas un silence qui laisse
    l'interface croire qu'elle a enregistré quelque chose."""
    assert client.post("/api/preferences", json=patch).status_code == 400
    assert client.get("/api/preferences").json()["preferences"]["theme"] == "light"


def test_stored_garbage_falls_back_to_the_default(client):
    """Une valeur retirée d'une énumération entre deux versions ne doit pas
    remonter telle quelle jusqu'à l'interface."""
    from db.app_settings import set_setting

    set_setting("theme", "solarized")
    assert client.get("/api/preferences").json()["preferences"]["theme"] == "light"


def test_the_model_choice_is_the_table_of_models_itself(client):
    """Le vocabulaire de `llm_model` n'est pas écrit dans `preferences.py` : il
    EST la table des modèles. Ajouter un modèle suffit — la préférence, le
    `choices` servi à l'interface et les budgets temps suivent."""
    from config.settings import LLM_MODELS

    body = client.get("/api/preferences").json()
    assert body["preferences"]["llm_model"] == "auto"
    assert body["choices"]["llm_model"] == ["auto", *LLM_MODELS]


def test_every_model_name_survives_the_lowercasing_of_a_preference():
    """`_validate` met les valeurs en minuscules. Un `Qwen3:1.7B` ajouté à la
    table rendrait la préférence inécrivable (400) sans qu'aucun test ne le
    dise — l'interface proposerait un modèle qu'on ne peut pas choisir."""
    from services.preferences import PREFERENCES

    for value in PREFERENCES["llm_model"].choices:
        assert value == value.lower(), value


def test_a_model_retired_from_the_table_falls_back_to_auto(client):
    """Le modèle stocké a disparu du catalogue (version suivante) : on retombe
    sur « auto », qui choisira ce qui est là, au lieu de remonter un nom mort."""
    from db.app_settings import set_setting

    set_setting("llm_model", "gemma3:2b")
    assert client.get("/api/preferences").json()["preferences"]["llm_model"] == "auto"


def test_user_name_round_trip(client):
    assert client.post("/api/preferences/name", json={"name": "  Ada  "}).json()["user"]["name"] == "Ada"
    assert client.get("/api/preferences").json()["user"]["name"] == "Ada"
    assert client.post("/api/preferences/name", json={"name": "   "}).status_code == 400
