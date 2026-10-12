def test_lang_languages(client):
    langs = client.get("/api/lang/languages").json()
    assert isinstance(langs, list) and len(langs) >= 1
    assert {"code", "label", "flag"} <= set(langs[0])


def test_lang_profile(client):
    body = client.get("/api/lang/profile", params={"language": "anglais"}).json()
    assert "profile" in body and "progress" in body
    assert body["progress"]["total_sessions"] == 0


# ── Catalogue des types d'exercice et lectures du séquenceur ──────────────────

# Fake LLM (signature callback on_success/on_error, comme le code réel).
def _correct_incorrect(language, target_phrase, user_attempt, on_success, on_error, model=None):
    on_success({
        "verdict": "incorrect",
        "corrections": [{"original": "holaa", "corrected": "hola", "reason": "orthographe"}],
        "feedback": "presque",
        "score": 0.3,
    })


def test_session_types_catalogue(client):
    from db.lang_db import SESSION_TYPES_SEED

    types = [
        {"code": c, "phase": ph, "skill": sk, "label": lb, "render_kind": rk}
        for (c, ph, sk, lb, _desc, rk) in SESSION_TYPES_SEED
    ]
    assert len(types) == 22
    codes = {t["code"] for t in types}
    assert "revision_adaptative" in codes and "traduction_inverse" in codes
    assert "ecriture_decouverte" in codes  # phase écriture (scripts non-latins)
    # Types interactifs (correction côté client) — 4 render_kinds neufs.
    assert {"completion_choix", "remise_en_ordre", "appariement", "transformation"} <= codes
    assert {t["render_kind"] for t in types} >= {"cloze", "ordering", "matching", "transform"}
    assert all(t["render_kind"] for t in types)


def test_seed_session_types_idempotent(client):
    from db import get_connection
    from db.lang_db import seed_session_types

    seed_session_types()
    seed_session_types()
    n = get_connection().execute("SELECT COUNT(*) AS n FROM lang_session_types").fetchone()["n"]
    assert n == 22


def test_db_sequencer_reads(client):
    from db.lang_db import (
        get_last_session_type,
        get_or_create_lang_profile,
        get_session_types_for_phase,
        get_skill_distribution,
        save_lang_session,
    )

    prof = get_or_create_lang_profile(1, "italien")
    pid = prof["id"]
    save_lang_session(pid, 1, 600, 0.8, "dialogue_ecoute")      # skill comprehension_orale
    save_lang_session(pid, 2, 600, 0.7, "traduction_inverse")   # skill production_ecrite

    assert get_last_session_type(pid) == "traduction_inverse"
    assert get_skill_distribution(pid, window=7) == {"comprehension_orale": 1, "production_ecrite": 1}

    passive = {t["code"] for t in get_session_types_for_phase("passive")}
    assert "dialogue_ecoute" in passive          # phase passive
    assert "revision_adaptative" in passive       # phase 'any' toujours incluse
    assert "traduction_inverse" not in passive    # phase active exclue








def test_correct_route_persists_errors(client, monkeypatch):
    """Une correction incorrecte alimente lang_errors (boucle vers la révision)."""
    monkeypatch.setattr("services.lang.generate_lang_correction_async", _correct_incorrect)

    resp = client.post(
        "/api/lang/correct",
        json={"language": "espagnol", "target_phrase": "hola", "user_attempt": "holaa"},
    )
    assert resp.json()["verdict"] == "incorrect"

    from db.lang_db import get_lang_errors_for_revision, get_or_create_lang_profile

    pid = get_or_create_lang_profile(1, "espagnol")["id"]
    assert "holaa" in {e["word"] for e in get_lang_errors_for_revision(pid)}

