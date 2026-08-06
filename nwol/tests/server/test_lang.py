def test_lang_languages(client):
    langs = client.get("/api/lang/languages").json()
    assert isinstance(langs, list) and len(langs) >= 1
    assert {"code", "label", "flag"} <= set(langs[0])


def test_lang_profile(client):
    body = client.get("/api/lang/profile", params={"language": "anglais"}).json()
    assert "profile" in body and "progress" in body
    assert body["progress"]["total_sessions"] == 0


# ── Séquenceur adaptatif : catalogue, décisions, fallback, routes ──────────────

# Fakes LLM (signature callback on_success/on_error, comme le code réel).

def _choose_fail(state, available, on_success, on_error, model=None):
    on_error("LLM indisponible")


def _choose_ok(state, available, on_success, on_error, model=None):
    on_success({"chosen_type": "dialogue_ecoute", "reason": "test"})


def _content_ok(language, session_type, profile, weak_points, on_success, on_error, model=None, due_cards=None):
    on_success({
        "kind": "dialogue",
        "render_kind": "dialogue",
        "label": "Dialogue (écoute)",
        "session_type": session_type,
        "theme": "Salutations",
        "dialogue": [{"speaker": "A", "target": "hola", "phonetic": "", "translation": "salut"}],
        "notes": {},
        "vocabulary": [],
    })


def _correct_incorrect(language, target_phrase, user_attempt, on_success, on_error, model=None):
    on_success({
        "verdict": "incorrect",
        "corrections": [{"original": "holaa", "corrected": "hola", "reason": "orthographe"}],
        "feedback": "presque",
        "score": 0.3,
    })


def test_session_types_endpoint_lists_catalogue(client):
    types = client.get("/api/lang/session-types").json()
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
    from db import get_connection
    from db.lang_db import (
        get_last_session_type,
        get_or_create_lang_profile,
        get_session_types_for_phase,
        get_skill_distribution,
        log_sequencer_decision,
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

    log_sequencer_decision(pid, 3, "culture_courte", "raison")
    rows = get_connection().execute(
        "SELECT COUNT(*) AS n FROM lang_sequencer_log WHERE profile_id=?", (pid,)
    ).fetchone()["n"]
    assert rows == 1


def test_forced_revision_every_7_sessions(client):
    """À la 7e session, la révision est imposée SANS appel LLM."""
    from db.lang_db import get_or_create_lang_profile, save_lang_session
    from services.lang_sequencer import decide_session_type

    prof = get_or_create_lang_profile(1, "allemand")
    for i in range(1, 7):  # 6 sessions -> la prochaine est la n°7
        save_lang_session(prof["id"], i, 100, 0.5, "dialogue_lecture")

    chosen, reason = decide_session_type(prof)
    assert chosen == "revision_adaptative"
    assert "7" in reason


def test_fallback_deterministic_without_llm(client, monkeypatch):
    """LLM indisponible -> choix déterministe valide, jamais le dernier type."""
    monkeypatch.setattr("services.lang_sequencer.choose_session_type_async", _choose_fail)
    from db.lang_db import (
        get_or_create_lang_profile,
        get_session_types_for_phase,
        save_lang_session,
    )
    from services.lang_sequencer import decide_session_type

    prof = get_or_create_lang_profile(1, "espagnol")
    save_lang_session(prof["id"], 1, 100, 0.5, "dialogue_ecoute")  # prochaine session = n°2

    chosen, reason = decide_session_type(prof)
    valid = {t["code"] for t in get_session_types_for_phase("passive")}
    assert chosen in valid
    assert chosen != "dialogue_ecoute"  # règle anti-répétition
    assert "déterministe" in reason.lower()


def test_session_route_returns_typed_content(client, monkeypatch):
    monkeypatch.setattr("services.lang_sequencer.choose_session_type_async", _choose_ok)
    monkeypatch.setattr("services.lang.generate_session_content_async", _content_ok)

    body = client.post("/api/lang/session", json={"language": "espagnol"}).json()
    assert body["session_type"] == "dialogue_ecoute"
    assert body["render_kind"] == "dialogue"
    assert body["content"]["dialogue"][0]["target"] == "hola"


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


def test_session_complete_records_type(client):
    """La clôture enregistre la session avec son type (pour la répartition)."""
    from db.lang_db import get_last_session_type, get_or_create_lang_profile

    body = client.post(
        "/api/lang/session/complete",
        json={"language": "espagnol", "session_type": "vocabulaire_contextuel", "score": 0.9, "duration_s": 300},
    ).json()
    assert body["total_sessions"] == 1

    pid = get_or_create_lang_profile(1, "espagnol")["id"]
    assert get_last_session_type(pid) == "vocabulaire_contextuel"
