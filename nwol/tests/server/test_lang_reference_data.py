# Données de référence vues depuis le serveur (plan D3, D23) : injection
# versionnée au démarrage, clés du test de niveau jamais envoyées au front.
import copy


def _program(language):
    from services.lang_static import load_json

    return load_json("program", f"{language}.json")


def test_placement_keys_never_reach_the_client(client):
    items = client.get("/api/lang/espagnol/placement").json()["items"]
    assert items and all("answer" not in it and "program_point" not in it for it in items)


def test_reference_seeding_is_versioned(client, monkeypatch):
    """D23 : réinjecté seulement si le fichier a changé (empreinte)."""
    from db import get_connection
    from db import lang_episode_db as store
    from services import lang_static

    conn = get_connection()
    assert store.program_size("espagnol") == len(_program("espagnol")["points"])
    conn.execute("UPDATE lang_program_points SET title='modifié' WHERE language='espagnol' AND ord=1")
    lang_static.seed_lang_reference()  # même version : on ne touche à rien
    assert store.get_point_by_order("espagnol", 1)["title"] == "modifié"
    monkeypatch.setattr(lang_static, "source_version", lambda *parts: "nouvelle-version")
    lang_static.seed_lang_reference()
    assert store.get_point_by_order("espagnol", 1)["title"] != "modifié"


def test_invalid_program_is_never_injected(client, monkeypatch):
    from db import lang_episode_db as store
    from services import lang_static

    real = lang_static.load_json

    def broken(*parts):
        data = real(*parts)
        if parts == ("program", "espagnol.json"):
            data = copy.deepcopy(data)
            data["points"][0]["order"] = 42
        return data

    before = store.program_size("espagnol")
    monkeypatch.setattr(lang_static, "load_json", broken)
    monkeypatch.setattr(lang_static, "source_version", lambda *parts: "autre")
    report = lang_static.seed_lang_reference()
    assert report["program:espagnol"] == "invalide"
    assert store.program_size("espagnol") == before
