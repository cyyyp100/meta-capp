# Lectures quittées en fermant le logiciel (services/session) : closes au
# démarrage suivant, puis finalisées comme un sas de sortie passé.
#
# Retour d'usage (2026-10-21) : fermer la fenêtre en pleine lecture laissait la
# séance ouverte pour toujours — « Session en cours » dans « Ma progression »,
# jamais mesurée dans le profil, sans le bilan de Clikoda.
from datetime import date, datetime, timedelta, timezone

import pytest

STARTED_UTC = "2026-10-20 12:00:00"


def _import_doc(client, tmp_path, make_pdf):
    p = make_pdf(tmp_path / "m.pdf", ["Contenu de test"])
    return client.post("/api/library/import", json={"path": p}).json()["id"]


def _session(client, doc_id, *, started_at=STARTED_UTC):
    from db import get_connection

    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    conn = get_connection()
    with conn:
        conn.execute("UPDATE reading_sessions SET started_at=? WHERE id=?", (started_at, sid))
    return sid


def _local(utc: str, seconds: float) -> str:
    started = datetime.fromisoformat(utc).replace(tzinfo=timezone.utc).astimezone()
    return (started + timedelta(seconds=seconds)).replace(tzinfo=None).isoformat()


def _read_something(sid, *, minutes=15, measured=True):
    """Ce que le socket du lecteur laisse d'une lecture : pages lues, battement,
    courbe de jauges (amorce puis une mesure)."""
    from db.answers import save_answer
    from db.session_gauges import record_gauges
    from db.sessions import update_session_progress

    update_session_progress(sid, pages_read=4, duration_s=minutes * 60)
    record_gauges(sid, {"attention": 50.0, "retention": 50.0}, t=0.0)
    if measured:
        record_gauges(sid, {"attention": 70.0, "retention": 80.0}, t=300.0)
        save_answer(question_id=None, user_id=1, answer_text="a", verdict="correct", session_id=sid)


def test_a_session_left_open_is_closed_at_its_last_trace(client, tmp_path, make_pdf):
    """Close à l'heure de sa dernière trace (départ + temps de lecture + pauses),
    pas à l'heure du démarrage ; celle où rien n'a été lu (quittée depuis le sas)
    est effacée ; une séance terminée n'est pas touchée."""
    from db.session_pauses import save_pause
    from db.sessions import get_session
    from services.session import close_abandoned_sessions

    doc_id = _import_doc(client, tmp_path, make_pdf)
    left = _session(client, doc_id)
    _read_something(left, minutes=15)
    save_pause(left, {"started_at": "x", "duration_s": 120.0, "source": "manual", "ended_by": "resume"})
    untouched = _session(client, doc_id)
    finished = _session(client, doc_id)
    client.post(f"/api/session/{finished}/end", json={"duration_s": 42})
    before = get_session(finished)

    assert close_abandoned_sessions() == {"closed": [left], "deleted": [untouched]}

    closed = get_session(left)
    assert closed["duration_s"] == 15 * 60
    assert closed["ended_at"] == _local(STARTED_UTC, 15 * 60 + 120)
    assert closed["finalized_at"] is None  # la finalisation suit, en thread
    assert get_session(untouched) is None
    assert get_session(finished) == before
    assert close_abandoned_sessions() == {"closed": [], "deleted": []}


def test_the_heartbeat_never_rewrites_a_finished_session(client, tmp_path, make_pdf):
    """Le battement du socket peut arriver après « Terminer » : la durée posée
    par `/end` (celle du client) reste."""
    from db.sessions import get_session, update_session_progress

    sid = _session(client, _import_doc(client, tmp_path, make_pdf))
    update_session_progress(sid, duration_s=300)
    update_session_progress(sid, duration_s=120)  # ne fait que croître
    assert get_session(sid)["duration_s"] == 300
    client.post(f"/api/session/{sid}/end", json={"duration_s": 280})
    update_session_progress(sid, duration_s=900)
    assert get_session(sid)["duration_s"] == 280


def test_a_pending_session_is_finalized_once_like_a_skipped_exit(
    client, tmp_path, make_pdf, monkeypatch, no_startup_session_finalize,
):
    """Comme « Passer » au sas : le bilan de Clikoda (persisté, relu dans « Ma
    progression »), puis la finalisation sans réponse — le profil glisse, la
    série compte le jour de la SÉANCE. Une seule fois : ni un second démarrage,
    ni un `/finalize` tardif ne font glisser le profil deux fois."""
    import llm.ollama_client as ollama_client
    from db.metacog import get_history_by_criterion
    from db.sessions import get_session
    from db.user import get_streak
    from services.session import close_abandoned_sessions

    def summary(_context, ok, _err):
        ok({"session_summary": {"qualitative_summary": "Bonne séance, régulière.", "metacognitive_questions": []}})

    monkeypatch.setattr(ollama_client, "generate_session_summary_async", summary)
    finalize_pending_sessions = no_startup_session_finalize

    sid = _session(client, _import_doc(client, tmp_path, make_pdf))
    _read_something(sid)
    close_abandoned_sessions()

    assert finalize_pending_sessions() == [sid]
    session = get_session(sid)
    assert session["finalized_at"]
    assert session["analysis"] == "Bonne séance, régulière."
    moved = {c for c, rows in get_history_by_criterion(1).items() if any(r[0] == sid for r in rows)}
    assert {"attention", "retention"} <= moved
    assert get_streak(1)["last_study_day"] == _local(STARTED_UTC, 0)[:10]

    history = get_history_by_criterion(1)
    assert finalize_pending_sessions() == []
    client.post(f"/api/session/{sid}/finalize", json={"responses": [], "questions": []})
    assert get_history_by_criterion(1) == history

    detail = client.get(f"/api/progress/session/{sid}").json()
    assert detail["completed"] is True
    assert detail["analysis"] == "Bonne séance, régulière."


def test_economy_mode_finalizes_without_asking_the_llm(
    client, tmp_path, make_pdf, monkeypatch, no_startup_session_finalize,
):
    """Mode économe : pas de travail de fond pour le modèle. Le profil glisse,
    le bilan reste vide, et rien n'est demandé au LLM."""
    import llm.ollama_client as ollama_client
    from db.sessions import get_session
    from services import llm_models
    from services import session as session_service
    from services.session import close_abandoned_sessions

    asked: list[str] = []
    monkeypatch.setattr(llm_models, "economy", lambda: True)
    monkeypatch.setattr(ollama_client, "generate_session_summary_async", lambda *a: asked.append("summary"))
    monkeypatch.setattr(session_service, "_update_general_analysis", lambda *a: asked.append("profile"))

    sid = _session(client, _import_doc(client, tmp_path, make_pdf))
    _read_something(sid)
    close_abandoned_sessions()
    assert no_startup_session_finalize() == [sid]
    assert asked == []
    session = get_session(sid)
    assert session["finalized_at"] and session["analysis"] is None


def test_the_server_start_closes_sessions_left_open(client, tmp_path, make_pdf):
    """Branché au démarrage : un nouveau serveur sur la même base clôt la séance
    avant la première requête — la frise ne dit plus « Session en cours »."""
    from fastapi.testclient import TestClient

    from server.app import create_app

    sid = _session(client, _import_doc(client, tmp_path, make_pdf))
    _read_something(sid)
    row = next(r for r in client.get("/api/progress/sessions").json()["sessions"] if r["session_id"] == sid)
    assert row["completed"] is False

    with TestClient(create_app(), base_url="http://127.0.0.1:8756") as restarted:
        restarted.headers["host"] = "127.0.0.1:8756"
        rows = restarted.get("/api/progress/sessions").json()["sessions"]
    row = next(r for r in rows if r["session_id"] == sid)
    assert row["completed"] is True


@pytest.mark.parametrize(
    "last,day,expected",
    [
        ("2026-10-19", date(2026, 10, 20), 2),  # la veille : la série avance
        ("2026-10-21", date(2026, 10, 20), 1),  # un jour déjà dépassé : rien ne bouge
        ("2026-10-20", date(2026, 10, 20), 1),  # le même jour : rien ne bouge
    ],
)
def test_a_study_day_can_be_the_day_of_the_session(client, last, day, expected):
    from db import get_connection
    from db.user import record_study_day

    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO login_streak (user_id, streak, longest_streak, last_study_day) VALUES (1, 1, 1, ?)",
            (last,),
        )
    record_study_day(1, day=day)
    # La série ÉCRITE : `get_streak` la lit par rapport à aujourd'hui, et l'affiche
    # à zéro passé le jour de grâce — ce test ne passait que les 20 et 21 octobre.
    row = conn.execute("SELECT streak FROM login_streak WHERE user_id=1").fetchone()
    assert row["streak"] == expected


def test_the_offline_fallback_is_never_stored_as_an_analysis(client, tmp_path, make_pdf):
    """Ollama absent : le sas affiche le texte générique du repli, mais « Ma
    progression » ne le relit pas comme le bilan de la séance."""
    from db.sessions import get_session

    sid = _session(client, _import_doc(client, tmp_path, make_pdf))
    client.post(f"/api/session/{sid}/end", json={"duration_s": 30})
    assert client.get(f"/api/session/{sid}/analysis").status_code == 200
    assert get_session(sid)["analysis"] is None
