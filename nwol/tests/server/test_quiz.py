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
