import pytest


def _import_doc(client, tmp_path):
    import fitz

    p = tmp_path / "m.pdf"
    d = fitz.open()
    page = d.new_page()
    page.insert_text((72, 72), "Contenu de test")
    d.save(str(p))
    d.close()
    return client.post("/api/library/import", json={"path": str(p)}).json()["id"]


def test_session_lifecycle_and_metrics(client, tmp_path):
    doc_id = _import_doc(client, tmp_path)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    assert isinstance(sid, int)

    # Semer des réponses pour cette session.
    from db.answers import save_answer

    save_answer(question_id=None, user_id=1, answer_text="a", verdict="correct", session_id=sid)
    save_answer(question_id=None, user_id=1, answer_text="b", verdict="partial", session_id=sid)
    save_answer(question_id=None, user_id=1, answer_text="c", verdict="incorrect", session_id=sid)

    m = client.post(f"/api/session/{sid}/end", json={"pages_read": 5, "duration_s": 120}).json()
    assert m["pages_read"] == 5
    assert m["duration_s"] == 120
    assert m["questions_answered"] == 3
    assert m["correct"] == 1
    assert m["success_rate"] == 50  # round(100*(1 + 0.5)/3)
    # Deux questions FIXES : l'étudiant écrit tout de suite. La troisième est
    # générée et arrive avec l'analyse (GET /session/{id}/analysis).
    assert len(m["reflection_questions"]) == 2


def test_session_finalize_updates_profile(client, tmp_path):
    from db.metacog import get_profile
    from db.session_reflections import get_session_reflections

    doc_id = _import_doc(client, tmp_path)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    before = (get_profile(1) or {}).get("sessions_count", 0)

    client.post(f"/api/session/{sid}/end", json={"pages_read": 3, "duration_s": 60})
    f = client.post(f"/api/session/{sid}/finalize", json={"responses": ["r1", "", "r3"]}).json()
    assert f["ok"] is True

    assert (get_profile(1) or {})["sessions_count"] == before + 1
    # 2 réponses non vides enregistrées.
    assert len(get_session_reflections(sid)) == 2


def test_finalize_nudges_profile_from_session_gauges(client):
    # Quand des jauges live ont été enregistrées, le profil complet glisse vers elles
    # (pas seulement les 3 critères du repli taux-de-réussite).
    from db.answers import save_answer
    from db.documents import upsert_document
    from db.metacog import get_profile
    from db.session_gauges import record_gauges
    from db.sessions import start_session
    from services.session import finalize_session

    doc_id = upsert_document("/tmp/nudge.pdf", "nudge.pdf", 5, "pymupdf", False)
    sid = start_session(doc_id)
    before = float((get_profile(1) or {})["creativity"])  # 50.0 par défaut
    # L'amorce d'abord (ce que fait `LiveGauges.attach_session`), puis la mesure :
    # sans ce repère, rien ne distingue une jauge exercée d'une jauge intacte.
    record_gauges(sid, {"creativity": 40.0, "attention": 40.0}, t=0.0)
    record_gauges(sid, {"creativity": 80.0, "attention": 80.0}, t=1.0)
    # Le profil ne bouge qu'à hauteur de ce qui a été mesuré : il faut au moins
    # une vraie mesure pour que la session pèse (cf. compute_confidence).
    save_answer(question_id=None, user_id=1, answer_text="a", verdict="correct", session_id=sid)

    finalize_session(sid, ["a", "b", "c"])

    after = float((get_profile(1) or {})["creativity"])
    assert after > before  # creativity tirée vers 80 (hors critères du repli)


def test_finalize_without_any_measure_leaves_profile_intact(client):
    """Anti-régression : une session sans la moindre mesure n'écrase pas le profil.

    Ouvrir un PDF, scroller, cliquer « Terminer » suffisait à tirer attention,
    compréhension et rétention vers le taux de réussite d'une session vide — soit
    0 — et donc vers EXACTEMENT 0 à la première session, où alpha vaut 1."""
    from db.documents import upsert_document
    from db.metacog import get_profile
    from db.sessions import start_session
    from services.session import finalize_session

    doc_id = upsert_document("/tmp/silent.pdf", "silent.pdf", 5, "pymupdf", False)
    sid = start_session(doc_id)
    before = dict(get_profile(1) or {})

    finalize_session(sid, ["", "", ""])

    after = get_profile(1) or {}
    for criterion in ("attention", "context_comprehension", "retention"):
        assert float(after[criterion]) == float(before[criterion])
    # La session a bien eu lieu : elle compte, elle ne mesure simplement rien.
    assert int(after["sessions_count"]) == int(before["sessions_count"]) + 1


def test_gauges_left_at_seed_do_not_drag_the_profile(client):
    """Anti-régression : une jauge jamais exercée ne doit pas peser.

    Une session démarre à profil × 0,8. Un critère que la séance n'a pas touché
    finit donc exactement 20 % sous le profil, et le remonter tel quel tirait le
    profil vers le bas à chaque session — sans qu'aucune mesure ne le justifie.
    C'est le dernier morceau de la famille du bug « le profil s'effondre »."""
    from db.answers import save_answer
    from db.documents import upsert_document
    from db.metacog import ensure_profile
    from db.session_gauges import record_gauges
    from db.sessions import start_session
    from metacog.gauges import initialize_session_gauges
    from services.session import finalize_session

    doc_id = upsert_document("/tmp/seed.pdf", "seed.pdf", 5, "pymupdf", False)
    sid = start_session(doc_id)
    before = dict(ensure_profile(1))
    seed = initialize_session_gauges(before)
    record_gauges(sid, seed, t=0.0)                      # l'amorce, figée à l'ouverture
    record_gauges(sid, dict(seed, curiosity=90.0), t=10.0)  # une seule jauge exercée
    save_answer(question_id=None, user_id=1, answer_text="a", verdict="correct", session_id=sid)

    finalize_session(sid, ["", "", ""])

    after = ensure_profile(1)
    assert float(after["curiosity"]) > float(before["curiosity"])
    for untouched in ("attention", "context_comprehension", "retention", "creativity"):
        assert float(after[untouched]) == pytest.approx(float(before[untouched]))


def test_session_analysis_carries_the_generated_question(client, tmp_path):
    """Le sas reçoit SA troisième question avec l'analyse, jamais une chaîne vide.

    Elle était générée par le prompt de session puis jetée : le sas affichait
    trois questions en dur."""
    from services.session import REFLECTION_QUESTIONS

    doc_id = _import_doc(client, tmp_path)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{sid}/end", json={"pages_read": 1, "duration_s": 30})

    body = client.get(f"/api/session/{sid}/analysis").json()
    question = body["question"]
    assert question.strip() and question.endswith("?")
    assert question not in REFLECTION_QUESTIONS  # jamais un doublon des fixes


def test_finalize_persists_the_generated_question_text(client, tmp_path):
    """La 3e réflexion est persistée sous SON intitulé, pas « Réflexion 3 »."""
    from db.session_reflections import get_session_reflections

    doc_id = _import_doc(client, tmp_path)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{sid}/end", json={"pages_read": 1, "duration_s": 30})
    generated = client.get(f"/api/session/{sid}/analysis").json()["question"]

    client.post(f"/api/session/{sid}/finalize", json={
        "responses": ["r1", "r2", "r3"],
        "questions": ["Q1 ?", "Q2 ?", generated],
    })

    stored = {r["question_text"] for r in get_session_reflections(sid)}
    assert generated in stored


def test_streak_is_a_pure_read_and_only_a_finished_session_advances_it(client, tmp_path):
    """`GET /api/streak` n'écrit rien : ouvrir l'app n'est pas étudier.

    C'est le défaut que la v27 corrige — la série s'incrémentait dans ce GET, et
    un rechargement de page suffisait à la faire vivre."""
    before = client.get("/api/streak").json()
    assert before["streak"] == 0
    assert client.get("/api/streak").json()["streak"] == 0  # toujours pas d'écriture

    doc_id = _import_doc(client, tmp_path)
    sid = client.post("/api/session/start", json={"doc_id": doc_id}).json()["session_id"]
    client.post(f"/api/session/{sid}/end", json={"pages_read": 1, "duration_s": 30})
    client.post(f"/api/session/{sid}/finalize", json={"responses": ["r1"], "questions": ["Q1 ?"]})

    after = client.get("/api/streak").json()
    assert after["streak"] == 1
    assert after["longest_streak"] == 1
