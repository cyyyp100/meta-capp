# Tests de la refonte Quiz : QCM (distracteurs LLM) + analyse/conseil de cours.
from __future__ import annotations


def _seed_subject_questions(subject: str = "physique", with_answers: bool = True) -> tuple[int, list[int]]:
    """Crée un document avec une matière + 2 questions de lecture (scope 'page')."""
    from db.documents import upsert_document
    from db.questions import save_question

    doc_id = upsert_document(
        path=f"/tmp/{subject}.pdf",
        filename=f"{subject}.pdf",
        page_count=10,
        engine="test",
        has_toc=False,
        subject=subject,
    )
    qids: list[int] = []
    for i in range(2):
        qids.append(
            save_question(
                doc_id,
                "page",
                f"Page {i + 1}",
                i + 1,
                i + 1,
                {
                    "question": f"Quelle est la notion {i + 1} en {subject} ?",
                    "question_type": "open",
                    "answer": f"Réponse {i + 1}" if with_answers else "",
                    "source_context": f"Le passage {i + 1} explique en détail la notion étudiée.",
                },
            )
        )
    return doc_id, qids


def _fake_distractors(context, on_success, on_error, model=None):
    result = {}
    for item in context.get("items") or []:
        answer = (item.get("answer") or "Bonne réponse").strip()
        result[int(item["id"])] = {"answer": answer, "distractors": ["Faux A", "Faux B", "Faux C"]}
    on_success(result)


def _fail_distractors(context, on_success, on_error, model=None):
    on_error("LLM indisponible")


def test_quiz_subjects_lists_available(client):
    """GET /quiz/subjects ne liste que les matières ayant des questions, avec l'effectif."""
    _seed_subject_questions("physique")
    resp = client.get("/api/quiz/subjects")
    assert resp.status_code == 200
    subjects = {row["subject"]: row["count"] for row in resp.json()}
    assert subjects.get("physique") == 2


def test_quiz_questions_build_mcq(client, monkeypatch):
    """Chaque QCM a 4 choix mélangés, uniques, contenant la bonne réponse."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    _seed_subject_questions("physique")

    resp = client.get("/api/quiz/questions", params={"subject": "physique"})
    assert resp.status_code == 200
    quiz = resp.json()
    assert len(quiz) == 2
    for q in quiz:
        assert q["answer"]
        choices = q["choices"]
        assert isinstance(choices, list) and len(choices) == 4
        assert len(set(choices)) == 4
        assert q["answer"] in choices
        assert q["document_id"] is not None


def test_quiz_questions_fallback_on_llm_failure(client, monkeypatch):
    """Si le LLM échoue, une question avec réponse stockée dégrade en question ouverte."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fail_distractors)
    _seed_subject_questions("physique", with_answers=True)

    resp = client.get("/api/quiz/questions", params={"subject": "physique"})
    assert resp.status_code == 200
    quiz = resp.json()
    assert len(quiz) == 2
    for q in quiz:
        assert q["choices"] is None  # repli question ouverte
        assert q["answer"]


def test_quiz_analysis_enriches_document_id(client, monkeypatch):
    """L'analyse enrichit chaque cours conseillé avec un document_id pour le deep-link."""

    def _fake_analysis(context, on_success, on_error, model=None):
        on_success(
            {
                "analysis": "Quelques lacunes en physique.",
                "weak_subjects": ["physique"],
                "courses_to_review": [
                    {
                        "title": "physique.pdf",
                        "subject": "physique",
                        "reason": "2 erreurs sur ce cours",
                        "document": "physique.pdf",
                        "chapter_title": "",
                    }
                ],
            }
        )

    monkeypatch.setattr("services.quiz.generate_quiz_session_analysis_async", _fake_analysis)

    answers = [
        {
            "question": "Q1",
            "user_answer": "faux",
            "verdict": "incorrect",
            "score": 0.0,
            "category": "physique",
            "source": "reading",
            "document": "physique.pdf",
            "document_id": 42,
            "chapter_title": None,
        }
    ]
    resp = client.post("/api/quiz/analysis", json={"answers": answers})
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"]
    assert body["courses_to_review"][0]["document_id"] == 42


def test_quiz_analysis_empty_history(client):
    """Sans historique, l'analyse renvoie une structure vide (pas d'appel LLM)."""
    resp = client.post("/api/quiz/analysis", json={"answers": []})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"analysis": "", "weak_subjects": [], "courses_to_review": []}


# ── Réutilisation des types de lecture dans le quiz ─────────────────────────

def _seed_typed_question(question_type: str, *, choices=None, subject: str = "maths") -> int:
    from db.documents import upsert_document
    from db.questions import save_question

    doc_id = upsert_document(
        path=f"/tmp/{subject}-{question_type}.pdf",
        filename=f"{subject}.pdf",
        page_count=4,
        engine="test",
        has_toc=False,
        subject=subject,
    )
    return save_question(
        doc_id, "page", "Page 1", 1, 1,
        {
            "question": f"Question de type {question_type} ?",
            "question_type": question_type,
            "choices": choices,
            "answer": "La réponse attendue",
            "source_context": "Un passage assez long pour rester exploitable hors lecture.",
        },
    )


def test_quiz_exposes_the_reading_question_type(client, monkeypatch):
    """Le type pilote le widget de réponse côté UI : il doit survivre au quiz."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    _seed_typed_question("comprehension")

    quiz = client.get("/api/quiz/questions", params={"subject": "maths"}).json()
    assert [q["question_type"] for q in quiz] == ["comprehension"]


def test_ordering_keeps_its_steps_and_skips_the_distractor_llm(client, monkeypatch):
    """Les étapes SONT la réponse : les mélanger à des distracteurs la détruirait."""
    seen: list[dict] = []

    def _spy(context, on_success, on_error, model=None):
        seen.extend(context.get("items") or [])
        on_success({})

    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _spy)
    steps = ["Poser les hypothèses", "Appliquer le théorème", "Conclure"]
    _seed_typed_question("ordering", choices=steps)

    quiz = client.get("/api/quiz/questions", params={"subject": "maths"}).json()
    assert len(quiz) == 1
    assert quiz[0]["question_type"] == "ordering"
    assert quiz[0]["choices"] == steps
    assert seen == []


def test_reflexive_types_never_reach_the_quiz(client, monkeypatch):
    """« Comment as-tu trouvé ta réponse ? » n'a aucun sens hors de la lecture."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    _seed_typed_question("metacognition", subject="philosophie")
    _seed_typed_question("connection", subject="philosophie")
    _seed_typed_question("application", subject="philosophie")

    quiz = client.get("/api/quiz/questions", params={"subject": "philosophie"}).json()
    assert [q["question_type"] for q in quiz] == ["application"]


def test_long_production_types_stay_open_instead_of_becoming_mcq(client, monkeypatch):
    """Un QCM sous un énoncé « explique en deux phrases » trahirait le type affiché."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    _seed_typed_question("teach_back", subject="chimie")

    quiz = client.get("/api/quiz/questions", params={"subject": "chimie"}).json()
    assert len(quiz) == 1
    assert quiz[0]["choices"] is None
    assert quiz[0]["answer"]


# ── Réglages de session : sujet libre + longueur ────────────────────────────

def test_quiz_completes_with_the_static_catalogue(client, monkeypatch):
    """Sans aucune lecture en base, une session reste jouable (catalogue statique)."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)

    quiz = client.get("/api/quiz/questions", params={"n": 5, "subject": "géographie"}).json()
    assert len(quiz) == 5
    assert {q["source"] for q in quiz} == {"static"}
    for q in quiz:
        assert q["answer"] in (q["choices"] or [])


def test_static_catalogue_covers_the_three_families(client):
    """Géographie, histoire et vocabulaire anglais : au moins dix questions chacun."""
    subjects = {row["subject"]: row["count"] for row in client.get("/api/quiz/subjects").json()}
    assert subjects.get("géographie", 0) >= 10
    assert subjects.get("histoire", 0) >= 10
    assert subjects.get("langues", 0) >= 10


def test_static_ids_never_collide_with_reading_ids(client, monkeypatch):
    """Deux réservoirs numérotés depuis 1 : sans décalage, une session mixte dupliquait un id."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    _seed_subject_questions("physique")

    quiz = client.get("/api/quiz/questions", params={"n": 8}).json()
    ids = [q["id"] for q in quiz]
    assert len(ids) == len(set(ids))
    assert {q["source"] for q in quiz} == {"reading", "static"}


def test_quiz_length_follows_the_requested_count(client, monkeypatch):
    """La longueur de session est celle demandée par l'apprenant."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)

    assert len(client.get("/api/quiz/questions", params={"n": 3}).json()) == 3
    assert len(client.get("/api/quiz/questions", params={"n": 12}).json()) == 12


def test_quiz_length_is_clamped_to_the_server_bounds(client, monkeypatch):
    """Le serveur borne : l'UI ne peut pas réclamer 999 questions."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    options = client.get("/api/quiz/options").json()

    quiz = client.get("/api/quiz/questions", params={"n": 999}).json()
    assert len(quiz) == options["max_length"]
    assert options["default_length"] in options["lengths"]


def test_topic_filters_the_static_catalogue(client, monkeypatch):
    """Un mot suffit à donner un sujet de session."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)

    quiz = client.get("/api/quiz/questions", params={"topic": "capitale", "n": 5}).json()
    assert len(quiz) == 5
    assert all("capitale" in q["question"].lower() for q in quiz)


def test_topic_finds_questions_through_the_course_they_came_from(client, monkeypatch):
    """Le sujet cherché est celui du COURS, pas forcément un mot de l'énoncé."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    from db.documents import update_document_digest

    doc_id, _ = _seed_subject_questions("physique")
    update_document_digest(
        doc_id, "physique",
        "Cours d'introduction à la thermodynamique et aux transferts de chaleur.",
        ["thermodynamique", "entropie"],
    )

    quiz = client.get("/api/quiz/questions", params={"topic": "thermodynamique", "n": 5}).json()
    assert len(quiz) == 2  # les deux questions du cours, et rien d'autre
    assert {q["source"] for q in quiz} == {"reading"}
    # Aucun énoncé ne contient le mot : c'est bien la fiche du document qui a servi.
    assert all("thermodynamique" not in q["question"].lower() for q in quiz)


def test_topic_without_any_match_returns_nothing(client, monkeypatch):
    """Mieux vaut une session vide (et le dire) qu'un quiz hors sujet."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)

    assert client.get("/api/quiz/questions", params={"topic": "cryptozoologie"}).json() == []


def test_quiz_finalize_goes_through_the_shared_metacog_finalisation(client, monkeypatch):
    """Le sas de sortie du quiz emprunte le MÊME chemin qu'une fin de lecture."""
    seen: dict = {}

    def _fake_nudge(user_id, score, responses, metrics, session_id=None, session_gauges=None):
        seen.update(
            user_id=user_id, score=score, responses=responses,
            metrics=metrics, session_id=session_id,
        )
        return {}

    monkeypatch.setattr("services.session.nudge_metacog_profile", _fake_nudge)

    resp = client.post(
        "/api/quiz/finalize",
        json={
            "responses": ["Les capitales", "Les dates", "En me relisant"],
            "score": 80.0,
            "questions_answered": 10,
            "correct": 8,
            "duration_s": 300,
            "subject": "géographie",
            "topic": "capitales",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "score": 80.0}
    assert seen["session_id"] is None  # un quiz n'est pas une session de lecture
    assert seen["score"] == 80.0
    assert len(seen["responses"]) == 3
    assert seen["metrics"]["questions_answered"] == 10
    assert seen["metrics"]["success_rate"] == 80
    assert seen["metrics"]["topic"] == "capitales"
