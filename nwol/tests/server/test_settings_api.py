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


def test_user_name_round_trip(client):
    assert client.post("/api/preferences/name", json={"name": "  Ada  "}).json()["user"]["name"] == "Ada"
    assert client.get("/api/preferences").json()["user"]["name"] == "Ada"
    assert client.post("/api/preferences/name", json={"name": "   "}).status_code == 400
