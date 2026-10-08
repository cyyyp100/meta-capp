"""« Ma progression » : exposer ce que la base tenait déjà (§ B4).

`metacog_history`, `session_gauges`, `session_reflections` et `page_dwell`
étaient écrits depuis des mois et aucun routeur ne les exposait. Ces tests
vérifient que la timeline et le détail disent la vérité — en particulier sur les
jauges restées à leur amorce, qui ne sont PAS des mesures.
"""
from __future__ import annotations


def _import_doc(client, tmp_path, make_pdf):
    path = make_pdf(tmp_path / "progress.pdf", ["Contenu de test pour la progression."])
    return client.post("/api/library/import", json={"path": path}).json()["id"]


def _read_pages(session_id: int, dwell: dict[int, float]) -> None:
    """Ce qu'écrit le socket du lecteur pendant la séance : le temps par page,
    et le compte des pages LUES (au moins PAGE_READ_MIN_DWELL_S)."""
    from config.settings import PAGE_READ_MIN_DWELL_S
    from db.page_dwell import save_page_dwell
    from db.sessions import update_session_progress

    save_page_dwell(session_id, dwell, {page: 1 for page in dwell})
    update_session_progress(
        session_id, pages_read=sum(1 for seconds in dwell.values() if seconds >= PAGE_READ_MIN_DWELL_S),
    )


def test_timeline_is_empty_on_a_fresh_database(client):
    body = client.get("/api/progress/sessions").json()
    assert body["sessions"] == []
    assert "attention" in body["criteria"]


def test_a_finished_session_appears_with_its_reflections(client, tmp_path, make_pdf):
    doc_id = _import_doc(client, tmp_path, make_pdf)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    _read_pages(sid, {1: 2.0, 2: 12.5, 3: 40.0, 4: 6.0})
    client.post(f"/api/session/{sid}/end", json={"duration_s": 420})
    client.post(f"/api/session/{sid}/finalize", json={
        "responses": ["J'ai compris le théorème central.", ""],
        "questions": ["Qu'as-tu compris ?", "Quel point reste flou ?"],
    })

    row = client.get("/api/progress/sessions").json()["sessions"][0]
    assert row["session_id"] == sid
    assert row["completed"] is True
    assert row["pages_read"] == 3
    assert row["has_reflections"] is True

    detail = client.get(f"/api/progress/session/{sid}").json()
    # Les mots de l'apprenant sont relus TELS QUELS : c'est le point de tout
    # l'écran, et une reformulation le viderait de son sens.
    answers = [r["answer"] for r in detail["reflections"]]
    assert "J'ai compris le théorème central." in answers
    assert detail["metrics"]["pages_read"] == 3
    # « Où tu as ralenti » : les pages lues seulement, pas celle qu'on a traversée.
    assert [row["page"] for row in detail["page_dwell"]] == [2, 3, 4]


def test_gauges_left_at_their_seed_are_not_reported_as_measured(client, tmp_path, make_pdf):
    """Une session démarre à profil × 0,8. Une jauge que la séance n'a pas
    exercée finit exactement à son amorce — la présenter comme une mesure est
    l'erreur que `services/session._measured_gauges` évite déjà côté profil."""
    from db.session_gauges import record_gauges

    doc_id = _import_doc(client, tmp_path, make_pdf)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    record_gauges(sid, {"attention": 40.0, "curiosity": 40.0}, t=0.0)
    record_gauges(sid, {"attention": 72.0, "curiosity": 40.0}, t=60.0)
    client.post(f"/api/session/{sid}/end", json={"duration_s": 60})

    gauges = client.get(f"/api/progress/session/{sid}").json()["gauges"]
    assert gauges["measured"] == ["attention"]
    assert gauges["seed"]["attention"] == 40.0
    assert len(gauges["series"]["attention"]) == 2


def test_pauses_are_listed_and_summed_but_kept_out_of_reading_time(client, tmp_path, make_pdf):
    """Les pauses de la séance : chacune avec ce qui l'a précédée, et leur
    total à part — `duration_s` reste du temps de lecture."""
    from db.session_pauses import save_pause

    doc_id = _import_doc(client, tmp_path, make_pdf)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    save_pause(sid, {"started_at": "2026-09-23T10:00:00", "page": 2, "duration_s": 300.0,
                     "planned_s": 300.0, "source": "suggested", "after_recommendation": True,
                     "recommendation_kind": "suggest_pause", "recommendation_delay_s": 12.0,
                     "attention_at_start": 35.0, "ended_by": "resume"})
    save_pause(sid, {"started_at": "2026-09-23T10:20:00", "page": 4, "duration_s": 120.0,
                     "source": "manual", "ended_by": "resume"})
    metrics = client.post(f"/api/session/{sid}/end", json={"duration_s": 900}).json()
    assert metrics["duration_s"] == 900
    assert metrics["pauses"] == 2
    assert metrics["pause_s"] == 420
    assert metrics["pauses_after_recommendation"] == 1

    pauses = client.get(f"/api/progress/session/{sid}").json()["pauses"]
    assert [p["source"] for p in pauses] == ["suggested", "manual"]
    assert pauses[0]["after_recommendation"] is True
    assert pauses[1]["after_recommendation"] is False
    assert pauses[1]["recommendation_kind"] is None


def test_unknown_session_is_a_404(client):
    assert client.get("/api/progress/session/424242").status_code == 404


def test_weekly_recap_counts_only_finished_sessions(client, tmp_path, make_pdf):
    doc_id = _import_doc(client, tmp_path, make_pdf)
    # Session ouverte, jamais close : elle ne doit pas entrer dans le bilan.
    client.post("/api/session/start", json={"doc_id": doc_id})

    assert client.get("/api/progress/weekly").json()["sessions"] == 0

    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    _read_pages(sid, {1: 30.0, 2: 45.0})
    client.post(f"/api/session/{sid}/end", json={"duration_s": 300})
    client.post(f"/api/session/{sid}/finalize", json={"responses": ["r"], "questions": ["q ?"]})

    recap = client.get("/api/progress/weekly").json()
    assert recap["sessions"] == 1
    assert recap["pages_read"] == 2
    assert recap["duration_s"] == 300


def test_sessions_are_named_after_their_document_and_reading_number(client, tmp_path, make_pdf):
    """La frise nomme chaque session « <titre du document> · Lecture n » — n
    compté PARMI les lectures de ce document. Le titre vient de
    `documents.filename` (la ligne n'a pas de colonne `title`) : le lire sous
    un autre nom rendait une chaîne vide et le même libellé pour toutes."""
    doc_id = _import_doc(client, tmp_path, make_pdf)
    other = client.post("/api/library/import", json={
        "path": make_pdf(tmp_path / "autre.pdf", ["Autre document."]),
    }).json()["id"]

    first = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{first}/end", json={"duration_s": 60})
    elsewhere = client.post("/api/session/start", json={"doc_id": other}).json()["session_id"]
    client.post(f"/api/session/{elsewhere}/end", json={"duration_s": 60})
    second = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{second}/end", json={"duration_s": 60})

    rows = {r["session_id"]: r for r in client.get("/api/progress/sessions").json()["sessions"]}
    assert rows[first]["document_title"] == "progress.pdf"
    assert rows[first]["reading_index"] == 1
    assert rows[second]["reading_index"] == 2
    # L'autre document a sa propre numérotation.
    assert rows[elsewhere]["document_title"] == "autre.pdf"
    assert rows[elsewhere]["reading_index"] == 1

    detail = client.get(f"/api/progress/session/{second}").json()
    assert detail["document"]["title"] == "progress.pdf"
    assert detail["reading_index"] == 2


# ── Trois catégories : lecture, quiz, langue ─────────────────────────────────

def _quiz(client, verdicts=("correct", "correct", "incorrect")) -> int:
    answers = [
        {"question": f"Q{i} ?", "question_type": "qcm", "category": "géographie", "source": "static",
         "user_answer": "x", "verdict": verdict, "response_time_ms": 2000}
        for i, verdict in enumerate(verdicts)
    ]
    sid = client.post("/api/quiz/session", json={"answers": answers, "duration_s": 60}).json()["session_id"]
    client.post("/api/quiz/finalize", json={"session_id": sid})
    return sid


def test_quiz_sessions_join_the_timeline_under_their_own_category(client, tmp_path, make_pdf):
    doc_id = _import_doc(client, tmp_path, make_pdf)
    reading = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{reading}/end", json={"duration_s": 60})
    quiz = _quiz(client)

    body = client.get("/api/progress/sessions").json()
    assert {(row["kind"], row["session_id"]) for row in body["sessions"]} == {
        ("reading", reading), ("quiz", quiz),
    }
    assert body["counts"] == {"reading": 1, "quiz": 1, "lang": 0}
    row = next(r for r in body["sessions"] if r["kind"] == "quiz")
    assert row["quiz"]["questions_answered"] == 3 and row["quiz"]["success_rate"] == 67
    assert row["criteria_moved"] > 0

    only_quiz = client.get("/api/progress/sessions", params={"kind": "quiz"}).json()["sessions"]
    assert [r["kind"] for r in only_quiz] == ["quiz"]
    only_reading = client.get("/api/progress/sessions", params={"kind": "reading"}).json()["sessions"]
    assert [r["kind"] for r in only_reading] == ["reading"]


def test_every_category_shares_the_gauge_curve_and_the_profile_moves(client):
    """Le point commun des trois détails : la courbe des jauges pendant la séance
    (avec son amorce et ce qui a été mesuré) et ce qu'elle a déplacé."""
    sid = _quiz(client)
    detail = client.get(f"/api/progress/practice/{sid}").json()
    assert set(detail["gauges"]) == {"axis", "seed", "series", "measured"}
    moved = {change["criterion"] for change in detail["profile_changes"] if change["delta"]}
    assert moved and moved <= set(detail["gauges"]["measured"])

    reading_gauges = client.get("/api/progress/sessions").json()
    assert reading_gauges["sessions"][0]["kind"] == "quiz"


def test_unknown_practice_session_is_a_404(client):
    assert client.get("/api/progress/practice/424242").status_code == 404


def test_criteria_moved_counts_only_the_criteria_that_moved(client):
    """`update_profile` écrit une ligne pour les six critères, même ceux que la
    séance n'a pas mesurés (avant = après) : la frise ne compte que les vrais
    mouvements. Un QCM ne mesure que la rétention et l'attention."""
    sid = _quiz(client)
    row = client.get("/api/progress/sessions").json()["sessions"][0]
    changes = client.get(f"/api/progress/practice/{sid}").json()["profile_changes"]
    assert len(changes) == 6
    assert row["criteria_moved"] == 2
    assert {c["criterion"] for c in changes if abs(c["delta"]) >= 0.05} == {"retention", "attention"}


def test_weekly_recap_counts_quizzes_too(client):
    """Une semaine de quiz qui annonçait « rien à raconter » au-dessus de critères
    déplacés se contredisait : toutes les catégories comptent."""
    _quiz(client)
    recap = client.get("/api/progress/weekly").json()
    assert recap["sessions"] == 1
    assert recap["by_kind"] == {"reading": 0, "quiz": 1, "lang": 0}
    assert recap["duration_s"] == 60 and recap["pages_read"] == 0
