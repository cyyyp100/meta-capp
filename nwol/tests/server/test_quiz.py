# Tests du Quiz : tous les types de questions (choix, remise en ordre, rédaction),
# correction des réponses rédigées + analyse/conseil de cours.
from __future__ import annotations

from subject_helpers import complete_language_session, import_document, own


def _seed_subject_questions(
    subject: str = "physique",
    with_answers: bool = True,
    question_type: str = "open",
) -> tuple[int, list[int]]:
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
                    "question_type": question_type,
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
    """GET /quiz/subjects liste les matières de l'apprenant, avec l'effectif."""
    _seed_subject_questions("physique")
    resp = client.get("/api/quiz/subjects")
    assert resp.status_code == 200
    subjects = {row["subject"]: row["count"] for row in resp.json()}
    assert subjects == {"physique": 2}


def test_quiz_subjects_are_the_learner_subjects(client):
    """Le sélecteur propose les matières de l'apprenant — celles de son profil —,
    pas celles du catalogue : une base neuve n'en a aucune, et deux apprenants
    n'ont pas les mêmes."""
    assert client.get("/api/quiz/subjects").json() == []

    # Un document importé, pas encore lu : la matière existe, sans question à jouer.
    import_document("physique")
    assert client.get("/api/quiz/subjects").json() == [
        {"subject": "physique", "kind": "discipline", "flag": "", "count": 0},
    ]
    # Une matière du catalogue devient jouable dès qu'elle est à l'apprenant.
    import_document("histoire")
    subjects = {row["subject"]: row for row in client.get("/api/quiz/subjects").json()}
    assert set(subjects) == {"physique", "histoire"}
    assert subjects["histoire"]["count"] >= 10

    # La même liste, dans le même ordre, que les cartes du profil.
    profile = [s["subject"] for s in client.get("/api/stats/overview").json()["subjects"]]
    assert [row["subject"] for row in client.get("/api/quiz/subjects").json()] == profile


def test_a_language_is_a_quiz_subject_once_practised(client):
    """Une langue seulement ouverte n'est pas une matière ; après une séance, elle
    l'est, avec son drapeau et le vocabulaire du catalogue."""
    complete_language_session("anglais", status="in_progress")
    assert client.get("/api/quiz/subjects").json() == []

    complete_language_session("anglais")
    assert client.get("/api/quiz/subjects").json() == [
        {"subject": "anglais", "kind": "language", "flag": "🇬🇧", "count": 10},
    ]


def test_the_catalogue_never_hands_out_a_subject(client, monkeypatch):
    """Le catalogue complète les matières de l'apprenant ; il ne lui en donne pas.

    Il servait jadis tout son contenu à une base neuve, et chaque réponse créait
    la matière dans le profil : tout le monde finissait avec Histoire et
    Géographie."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    import_document("physique")

    assert client.get("/api/quiz/questions", params={"n": 5}).json() == []
    assert client.get("/api/quiz/questions", params={"n": 5, "interleaved": "true"}).json() == []
    assert client.get("/api/quiz/questions", params={"subject": "géographie"}).json() == []


def test_an_answer_in_an_unknown_category_creates_no_subject(client):
    """Seule une matière du vocabulaire a un niveau ; une variante d'écriture
    rejoint sa clé."""
    body = client.post("/api/quiz/answer", json={"category": "sous-marinologie", "correct": True}).json()
    assert body["updated"] is False
    body = client.post("/api/quiz/answer", json={"category": "Maths", "correct": True}).json()
    assert body["category"] == "mathématiques"


def test_quiz_questions_build_mcq(client, monkeypatch):
    """Un QCM a 4 choix mélangés, uniques, contenant la bonne réponse."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    _seed_subject_questions("physique", question_type="qcm")

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


def test_written_types_stay_written_and_skip_the_distractor_llm(client, monkeypatch):
    """Une question à rédiger reste à rédiger : le quiz n'en fait pas un QCM.

    C'était le défaut du quiz : tout type à réponse courte était converti en
    questionnaire à choix multiples, si bien qu'une session n'affichait jamais
    autre chose que des QCM."""
    seen: list[dict] = []

    def _spy(context, on_success, on_error, model=None):
        seen.extend(context.get("items") or [])
        on_success({})

    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _spy)
    _seed_subject_questions("physique", question_type="open")

    quiz = client.get("/api/quiz/questions", params={"subject": "physique"}).json()
    assert len(quiz) == 2
    for q in quiz:
        assert q["question_type"] == "open"
        assert q["choices"] is None
        assert q["answer"]
    assert seen == []


def test_quiz_questions_fallback_on_llm_failure(client, monkeypatch):
    """Si les distracteurs manquent, le QCM dégrade en question à rédiger."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fail_distractors)
    _seed_subject_questions("physique", with_answers=True, question_type="qcm")

    resp = client.get("/api/quiz/questions", params={"subject": "physique"})
    assert resp.status_code == 200
    quiz = resp.json()
    assert len(quiz) == 2
    for q in quiz:
        assert q["choices"] is None  # repli : réponse rédigée
        assert q["answer"]


def _capture_analysis(monkeypatch, *, analysis: str = "Bilan.", fail: bool = False) -> list[dict]:
    """Remplace l'appel LLM d'analyse ; renvoie la liste des contextes reçus."""
    seen: list[dict] = []

    def _fake(context, on_success, on_error, model=None):
        seen.append(context)
        if fail:
            on_error("LLM indisponible")
            return
        # Le LLM « propose » un cours qui n'existe pas : il doit être ignoré.
        on_success({"analysis": analysis, "courses_to_review": [{"title": "git commit"}]})

    monkeypatch.setattr("services.quiz.generate_quiz_session_analysis_async", _fake)
    return seen


def _answer(verdict: str, *, category: str = "physique", doc_id=None, document=None,
            chapter=None, source: str | None = None) -> dict:
    return {
        "question": "Q",
        "user_answer": "R",
        "verdict": verdict,
        "score": {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[verdict],
        "category": category,
        "source": source or ("reading" if doc_id is not None else "static"),
        "document": document,
        "document_id": doc_id,
        "chapter_title": chapter,
    }


def test_quiz_analysis_courses_are_library_documents_only(client, monkeypatch):
    """Les cours à renforcer sont calculés depuis les questions de LECTURE manquées.

    Une question du catalogue statique n'a pas de cours : elle n'en produit aucun,
    et ce que le LLM « recommande » de son côté n'arrive jamais à l'écran."""
    _capture_analysis(monkeypatch)
    doc_id, _ = _seed_subject_questions("physique")
    answers = [
        _answer("incorrect", doc_id=doc_id, document="physique.pdf", chapter="Ondes"),
        _answer("partial", doc_id=doc_id, document="physique.pdf", chapter="Optique"),
        _answer("correct", doc_id=doc_id, document="physique.pdf", chapter="Ondes"),
        _answer("incorrect", category="informatique"),  # catalogue statique
    ]
    resp = client.post("/api/quiz/analysis", json={"answers": answers})
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == "Bilan."
    assert body["courses_to_review"] == [{
        "document_id": doc_id,
        "title": "physique.pdf",
        "subject": "physique",
        "chapters": ["Ondes", "Optique"],
        "answered": 3,
        "missed": 2,
    }]
    assert body["weak_subjects"] == ["informatique", "physique"]


def test_quiz_analysis_skips_missing_documents_and_mastered_courses(client, monkeypatch):
    """Document supprimé (ou id forgé) : pas de carte. Cours sans erreur : pas de carte."""
    _capture_analysis(monkeypatch)
    doc_id, _ = _seed_subject_questions("physique")
    answers = [
        _answer("correct", doc_id=doc_id, document="physique.pdf"),
        _answer("incorrect", doc_id=999_999, document="disparu.pdf"),
    ]
    body = client.post("/api/quiz/analysis", json={"answers": answers}).json()
    assert body["courses_to_review"] == []


def test_quiz_analysis_shows_the_current_document_title(client, monkeypatch):
    """Le titre affiché est relu en base : un renommage se voit dans le bilan."""
    from db.documents import rename_document

    _capture_analysis(monkeypatch)
    doc_id, _ = _seed_subject_questions("physique")
    rename_document(doc_id, "Cours de physique")
    answers = [_answer("incorrect", doc_id=doc_id, document="physique.pdf")]
    body = client.post("/api/quiz/analysis", json={"answers": answers}).json()
    assert body["courses_to_review"][0]["title"] == "Cours de physique"


def test_quiz_analysis_is_framed_by_the_session_settings(client, monkeypatch):
    """Matière et précision choisies au lancement atteignent le prompt, et seuls les
    niveaux des matières de la session l'accompagnent (pas le profil entier)."""
    from db.subjects import update_subject_from_answer
    from db.user import DEFAULT_USER_ID

    update_subject_from_answer(DEFAULT_USER_ID, "informatique", True)
    update_subject_from_answer(DEFAULT_USER_ID, "histoire", False)
    seen = _capture_analysis(monkeypatch)
    answers = [_answer("incorrect", category="informatique"), _answer("correct", category="informatique")]
    settings = {"mode": "subject", "subject": "informatique", "topic": " git "}
    client.post("/api/quiz/analysis", json={"answers": answers, "settings": settings})

    context = seen[0]
    assert context["session"] == {
        "mode": "subject", "subject": "informatique", "topic": "git", "answered": 2,
    }
    assert [p["subject"] for p in context["subject_profiles"]] == ["informatique"]
    # Le score brut ne part pas au prompt : le LLM le recopiait (« score de 0.0 »).
    assert all("score" not in entry for entry in context["answers_history"])


def test_quiz_analysis_multi_mode_has_no_subject_nor_topic(client, monkeypatch):
    """Multi-apprentissage : matière et précision envoyées quand même sont ignorées."""
    seen = _capture_analysis(monkeypatch)
    settings = {"mode": "multi", "subject": "physique", "topic": "ondes"}
    client.post("/api/quiz/analysis", json={"answers": [_answer("correct")], "settings": settings})
    assert seen[0]["session"] == {"mode": "multi", "subject": None, "topic": None, "answered": 1}


def test_quiz_analysis_keeps_the_courses_when_the_llm_fails(client, monkeypatch):
    """Sans LLM, le bilan perd son texte, pas ses cours : ils sont calculés."""
    _capture_analysis(monkeypatch, fail=True)
    doc_id, _ = _seed_subject_questions("physique")
    answers = [_answer("incorrect", doc_id=doc_id, document="physique.pdf")]
    body = client.post("/api/quiz/analysis", json={"answers": answers}).json()
    assert body["analysis"] == ""
    assert [c["document_id"] for c in body["courses_to_review"]] == [doc_id]


def test_quiz_analysis_prompt_states_the_chosen_frame():
    """Le prompt nomme la matière et les mots-clés choisis, ou le multi-apprentissage."""
    from llm.prompts import build_quiz_session_analysis_prompt

    prompt = build_quiz_session_analysis_prompt(
        [], session={"mode": "subject", "subject": "informatique", "topic": "git", "answered": 4},
    )
    assert "informatique" in prompt and '"git"' in prompt
    multi = build_quiz_session_analysis_prompt([], session={"mode": "multi", "answered": 4})
    assert "multi-apprentissage" in multi and "mots-clés tapés" not in multi


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


def test_ordering_without_steps_is_dropped(client, monkeypatch):
    """Une remise en ordre sans étapes ne se joue pas : mieux vaut l'écarter."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    _seed_typed_question("ordering", choices=None, subject="svt")

    assert client.get("/api/quiz/questions", params={"subject": "svt"}).json() == []


# ── Correction des réponses rédigées (POST /api/quiz/evaluate) ──────────────

def _evaluator(verdict: str, **extra):
    """Faux évaluateur LLM ; enregistre le contexte reçu dans `seen`."""
    seen: list[dict] = []

    def _call(context, on_success, on_error, model=None):
        seen.append(context)
        on_success({"verdict": verdict, "feedback": "Un retour utile.", **extra})

    return _call, seen


def test_evaluate_grades_a_written_answer_with_the_llm(client, monkeypatch):
    """Sans cette correction, un type à rédiger n'aurait personne pour le juger."""
    evaluator, seen = _evaluator("partial", completion="Il manque la contrainte.")
    monkeypatch.setattr("services.quiz.evaluate_answer_async", evaluator)
    qid = _seed_typed_question("teach_back", subject="chimie")

    body = client.post("/api/quiz/evaluate", json={
        "question_id": qid,
        "question": "Question de type teach_back ?",
        "user_answer": "Ma tentative d'explication.",
        "question_type": "teach_back",
    }).json()

    assert body["verdict"] == "partial"
    assert body["score"] == 0.5
    assert body["graded"] is True
    assert body["feedback"] == "Un retour utile."
    assert body["completion"] == "Il manque la contrainte."
    assert body["expected_answer"] == "La réponse attendue"
    assert len(seen) == 1


def test_evaluate_corrects_from_the_stored_question_not_the_payload(client, monkeypatch):
    """La question persistée fait foi : réponse canonique ET passage d'origine."""
    evaluator, seen = _evaluator("correct")
    monkeypatch.setattr("services.quiz.evaluate_answer_async", evaluator)
    qid = _seed_typed_question("elaboration_why", subject="chimie")

    body = client.post("/api/quiz/evaluate", json={
        "question_id": qid,
        "question": "Énoncé réécrit par un client bavard",
        "user_answer": "Parce que la condition est nécessaire.",
        "answer": "Une réponse inventée côté client",
    }).json()

    assert body["verdict"] == "correct"
    assert body["score"] == 1.0
    context = seen[0]
    assert context["question"]["expected_answer"] == "La réponse attendue"
    assert context["question"]["question_type"] == "elaboration_why"
    assert context["paragraph"].startswith("Un passage assez long")


def test_evaluate_settles_a_choice_question_without_the_llm(client, monkeypatch):
    """Un QCM se corrige en comparant : appeler le LLM serait du temps perdu."""

    def _never(context, on_success, on_error, model=None):
        raise AssertionError("le LLM ne doit pas être appelé pour un QCM")

    monkeypatch.setattr("services.quiz.evaluate_answer_async", _never)
    choices = ["La réponse attendue", "Faux A", "Faux B", "Faux C"]
    qid = _seed_typed_question("qcm", choices=choices, subject="physique")

    body = client.post("/api/quiz/evaluate", json={
        "question_id": qid, "user_answer": "La réponse attendue",
    }).json()
    assert body["verdict"] == "correct"

    body = client.post("/api/quiz/evaluate", json={
        "question_id": qid, "user_answer": "Faux B",
    }).json()
    assert body["verdict"] == "incorrect"
    assert body["score"] == 0.0


def test_evaluate_gives_partial_credit_to_an_adjacent_swap(client, monkeypatch):
    """Séquence comprise, ordre non : même barème objectif que dans le lecteur."""

    def _never(context, on_success, on_error, model=None):
        raise AssertionError("une remise en ordre se corrige sans LLM")

    monkeypatch.setattr("services.quiz.evaluate_answer_async", _never)
    steps = ["Poser les hypothèses", "Appliquer le théorème", "Conclure"]
    qid = _seed_typed_question("ordering", choices=steps, subject="maths")

    swapped = "1. Appliquer le théorème\n2. Poser les hypothèses\n3. Conclure"
    body = client.post("/api/quiz/evaluate", json={
        "question_id": qid, "user_answer": swapped,
    }).json()
    assert body["verdict"] == "partial"
    assert body["score"] == 0.5


def test_evaluate_falls_back_to_self_grading_when_the_llm_is_down(client, monkeypatch):
    """Hors ligne, la session continue : l'UI reprend l'auto-évaluation."""

    def _down(context, on_success, on_error, model=None):
        on_error("Ollama injoignable")

    monkeypatch.setattr("services.quiz.evaluate_answer_async", _down)
    qid = _seed_typed_question("recall", subject="histoire")

    body = client.post("/api/quiz/evaluate", json={
        "question_id": qid, "user_answer": "Ce dont je me souviens.",
    }).json()
    assert body["graded"] is False
    assert body["verdict"] == ""
    assert body["expected_answer"] == "La réponse attendue"


def test_evaluate_counts_an_empty_answer_as_incorrect(client, monkeypatch):
    """« Je ne sais pas » : rien à juger, et surtout rien à demander au LLM."""

    def _never(context, on_success, on_error, model=None):
        raise AssertionError("une réponse vide ne se soumet pas au LLM")

    monkeypatch.setattr("services.quiz.evaluate_answer_async", _never)
    qid = _seed_typed_question("counterexample", subject="maths")

    body = client.post("/api/quiz/evaluate", json={
        "question_id": qid, "user_answer": "   ",
    }).json()
    assert body["verdict"] == "incorrect"
    assert body["score"] == 0.0
    assert body["expected_answer"] == "La réponse attendue"


def test_evaluate_handles_a_static_catalogue_question(client, monkeypatch):
    """Le catalogue statique n'est pas dans `questions` : le corps fait foi."""

    def _never(context, on_success, on_error, model=None):
        raise AssertionError("un QCM du catalogue se corrige sans LLM")

    monkeypatch.setattr("services.quiz.evaluate_answer_async", _never)
    from db.quiz_questions import STATIC_ID_OFFSET

    body = client.post("/api/quiz/evaluate", json={
        "question_id": STATIC_ID_OFFSET + 1,
        "question": "Quelle est la capitale de l'Australie ?",
        "question_type": "qcm",
        "answer": "Canberra",
        "choices": ["Canberra", "Sydney", "Melbourne", "Brisbane"],
        "user_answer": "Sydney",
    }).json()
    assert body["verdict"] == "incorrect"
    assert body["expected_answer"] == "Canberra"


def test_answer_keeps_the_partial_verdict(client):
    """Le booléen seul écrasait le « partiel » en « incorrect » côté rétention."""
    body = client.post(
        "/api/quiz/answer", json={"category": "maths", "correct": False, "verdict": "partial"},
    ).json()
    assert body["verdict"] == "partial"

    body = client.post("/api/quiz/answer", json={"category": "maths", "correct": True}).json()
    assert body["verdict"] == "correct"  # sans verdict, il est déduit du booléen


# ── Réglages de session : sujet libre + longueur ────────────────────────────

def test_quiz_completes_with_the_static_catalogue(client, monkeypatch):
    """Une matière importée mais pas encore lue se joue déjà : le catalogue la complète."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    own("géographie")

    quiz = client.get("/api/quiz/questions", params={"n": 5, "subject": "géographie"}).json()
    assert len(quiz) == 5
    assert {q["source"] for q in quiz} == {"static"}
    for q in quiz:
        assert q["answer"] in (q["choices"] or [])


def test_static_catalogue_covers_the_three_families(client):
    """Géographie, histoire et vocabulaire anglais : au moins dix questions chacun."""
    own("géographie", "histoire", "anglais")
    subjects = {row["subject"]: row["count"] for row in client.get("/api/quiz/subjects").json()}
    assert subjects.get("géographie", 0) >= 10
    assert subjects.get("histoire", 0) >= 10
    assert subjects.get("anglais", 0) >= 10


def test_static_ids_never_collide_with_reading_ids(client, monkeypatch):
    """Deux réservoirs numérotés depuis 1 : sans décalage, une session mixte dupliquait un id."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    _seed_subject_questions("physique")
    own("histoire")

    quiz = client.get("/api/quiz/questions", params={"n": 8}).json()
    ids = [q["id"] for q in quiz]
    assert len(ids) == len(set(ids))
    assert {q["source"] for q in quiz} == {"reading", "static"}


def test_quiz_length_follows_the_requested_count(client, monkeypatch):
    """La longueur de session est celle demandée par l'apprenant."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    own("géographie", "histoire")

    assert len(client.get("/api/quiz/questions", params={"n": 3}).json()) == 3
    assert len(client.get("/api/quiz/questions", params={"n": 12}).json()) == 12


def test_quiz_length_is_clamped_to_the_server_bounds(client, monkeypatch):
    """Le serveur borne : l'UI ne peut pas réclamer 999 questions."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    own("géographie", "histoire", "anglais")
    options = client.get("/api/quiz/options").json()

    quiz = client.get("/api/quiz/questions", params={"n": 999}).json()
    assert len(quiz) == options["max_length"]
    assert options["min_length"] <= options["default_length"] <= options["max_length"]

    # Le nombre est libre entre les bornes : l'UI le saisit au nombre près.
    quiz = client.get("/api/quiz/questions", params={"n": options["min_length"] + 4}).json()
    assert len(quiz) == options["min_length"] + 4


def test_topic_filters_the_static_catalogue(client, monkeypatch):
    """Un mot suffit à donner un sujet de session."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    own("géographie")

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


def test_topic_narrows_within_the_chosen_subject(client, monkeypatch):
    """La précision affine DANS la matière, elle ne la contourne pas.

    C'est la hiérarchie de l'écran de lancement : on choisit une matière, puis un
    mot plus précis qu'elle. Le mot ne doit donc jamais ramener une question
    d'une autre matière."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    from db.documents import update_document_digest

    doc_id, _ = _seed_subject_questions("physique")
    update_document_digest(
        doc_id, "physique",
        "Cours d'introduction à la thermodynamique et aux transferts de chaleur.",
        ["thermodynamique", "entropie"],
    )
    _seed_subject_questions("histoire")

    inside = client.get(
        "/api/quiz/questions", params={"subject": "physique", "topic": "thermodynamique"},
    ).json()
    assert len(inside) == 2
    assert {q["category"] for q in inside} == {"physique"}

    elsewhere = client.get(
        "/api/quiz/questions", params={"subject": "histoire", "topic": "thermodynamique"},
    ).json()
    assert elsewhere == []


def test_topic_without_any_match_returns_nothing(client, monkeypatch):
    """Mieux vaut une session vide (et le dire) qu'un quiz hors sujet."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)

    assert client.get("/api/quiz/questions", params={"topic": "cryptozoologie"}).json() == []


# ── Pratique entrelacée ─────────────────────────────────────────────────────

def test_interleaved_alternates_between_domains(client, monkeypatch):
    """Deux questions voisines viennent de domaines différents.

    C'est tout l'intérêt du mode : prendre les n premières d'un tirage aléatoire
    laisserait un domaine bien fourni rafler la session."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    _seed_subject_questions("physique")
    _seed_subject_questions("histoire")
    own("géographie")

    quiz = client.get("/api/quiz/questions", params={"n": 6, "interleaved": "true"}).json()
    assert len(quiz) == 6
    categories = [q["category"] for q in quiz]
    assert len(set(categories)) > 1
    # Trois matières, dont deux étoffées par le catalogue : il y a de quoi
    # alterner, donc aucun doublon consécutif n'est excusable ici.
    assert all(a != b for a, b in zip(categories, categories[1:]))


def test_interleaved_ignores_subject_and_topic(client, monkeypatch):
    """L'exclusivité est une règle serveur, pas seulement un grisage d'UI."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    _seed_subject_questions("physique")
    own("géographie")

    quiz = client.get(
        "/api/quiz/questions",
        params={"n": 6, "interleaved": "true", "subject": "physique", "topic": "capitale"},
    ).json()
    assert len(quiz) == 6
    # Ni le filtre de matière ni le filtre de sujet n'a réduit la session.
    assert len({q["category"] for q in quiz}) > 1


def test_interleaved_honours_the_requested_length(client, monkeypatch):
    """Le nombre de questions reste le seul réglage disponible dans ce mode."""
    monkeypatch.setattr("services.quiz.generate_quiz_distractors_async", _fake_distractors)
    own("géographie", "histoire")

    assert len(client.get(
        "/api/quiz/questions", params={"n": 5, "interleaved": "true"},
    ).json()) == 5


def test_quiz_finalize_goes_through_the_shared_metacog_finalisation(client, monkeypatch):
    """Le sas de sortie du quiz emprunte le MÊME chemin qu'une fin de lecture."""
    seen: dict = {}

    def _fake_nudge(user_id, score, responses, metrics, session_id=None, session_gauges=None, **extra):
        seen.update(
            user_id=user_id, score=score, responses=responses,
            metrics=metrics, session_id=session_id, kind=extra.get("kind"),
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
    assert seen["kind"] == "quiz"  # sans séance, il dit ce qu'il est : son poids est celui d'un quiz
    assert seen["score"] == 80.0
    assert len(seen["responses"]) == 3
    assert seen["metrics"]["questions_answered"] == 10
    assert seen["metrics"]["success_rate"] == 80
    assert seen["metrics"]["topic"] == "capitales"


# ── Rotation du stock : ne pas resservir les mêmes questions ─────────────────
#
# Ces tests décrivent le défaut d'origine : sans sujet libre, le `LIMIT` SQL VALAIT
# la longueur de session, donc `ORDER BY failed DESC, created_at DESC` choisissait
# le quiz à lui seul — deux sessions d'affilée sur une même matière rendaient
# exactement les mêmes questions, indéfiniment, et le stock ancien ne sortait jamais.

def _seed_many(subject: str = "physique", n: int = 60) -> int:
    """Un document + `n` questions de lecture jouables sur la même matière."""
    from db.documents import upsert_document
    from db.questions import save_question

    doc_id = upsert_document(
        path=f"/tmp/{subject}-stock.pdf",
        filename=f"{subject}-stock.pdf",
        page_count=n,
        engine="test",
        has_toc=False,
        subject=subject,
    )
    for i in range(n):
        save_question(
            doc_id, "page", f"Page {i + 1}", i + 1, i + 1,
            {
                "question": f"Quelle est la notion {i + 1} en {subject} ?",
                "question_type": "open",
                "answer": f"Réponse {i + 1}",
                "source_context": f"Le passage {i + 1} explique en détail la notion étudiée.",
            },
        )
    return doc_id


def _ids(client, **params) -> list[int]:
    resp = client.get("/api/quiz/questions", params=params)
    assert resp.status_code == 200
    return [q["id"] for q in resp.json()]


def test_two_sessions_in_a_row_do_not_repeat_the_same_questions(client):
    """Deux quiz consécutifs sur la même matière : le recouvrement doit être faible."""
    _seed_many("physique", 60)
    first = _ids(client, subject="physique", n=10)
    second = _ids(client, subject="physique", n=10)

    assert len(first) == len(second) == 10
    overlap = set(first) & set(second)
    # Avant : overlap == 10 (les mêmes questions, dans le même ordre).
    assert len(overlap) < 5, f"recouvrement trop fort : {sorted(overlap)}"


def test_every_question_of_the_stock_can_surface(client):
    """Aucune question n'est définitivement hors d'atteinte, même la plus ancienne."""
    _seed_many("physique", 30)
    seen: set[int] = set()
    for _ in range(20):
        seen.update(_ids(client, subject="physique", n=10))
    # Avant : seules les 10 plus récentes sortaient, quel que soit le nombre de tours.
    assert len(seen) == 30


def test_a_failed_question_keeps_priority_despite_the_cooldown(client):
    """La répétition espacée prime : une question ratée reste sur-représentée.

    Comparaison APPARIÉE avec ses voisines du même tirage plutôt qu'à un seuil
    absolu : le taux global dépend de l'amortissement, qui s'applique aussi à la
    question ratée (chaque fois qu'elle sort, elle est réamortie). C'est ce
    contrepoids qui borne le bonus — et c'est voulu : on veut la revoir souvent,
    pas la revoir à chaque session.

    Deux verrous, séparés exprès : le marquage `failed` (déterministe) puis la
    sur-représentation (statistique). Voir les commentaires en place.
    """
    from config.settings import QUIZ_SEARCH_POOL
    from db import get_connection
    from db.answers import save_answer
    from db.quiz_questions import get_quiz_base_questions
    from db.user import DEFAULT_USER_ID

    doc_id = _seed_many("physique", 40)
    qid = get_connection().execute(
        "SELECT id FROM questions WHERE document_id=? ORDER BY id LIMIT 1", (doc_id,),
    ).fetchone()["id"]
    save_answer(qid, DEFAULT_USER_ID, "à côté", verdict="incorrect")

    # Verrou 1, DÉTERMINISTE : la question est bien marquée « ratée » dans le
    # vivier. `services.quiz._weights` ne multiplie par QUIZ_FAILED_BONUS que si
    # cette colonne remonte — si la jointure sur `answers` ne voit pas la
    # réponse, il n'y a plus de bonus DU TOUT et le tirage devient uniforme.
    # Séparé du verrou statistique exprès : mélangés, un rouge ne disait pas
    # lequel des deux avait lâché, et l'écart mesuré (ratio ~1,0 au lieu de
    # ~1,8) ressemblait à de la malchance alors qu'il ne l'était pas.
    pool = get_quiz_base_questions(DEFAULT_USER_ID, QUIZ_SEARCH_POOL, "physique")
    marked = next((q for q in pool if q["id"] == qid), None)
    assert marked is not None and marked["failed"], (
        "la question ratée n'est pas marquée `failed` dans le vivier : le bonus "
        "de répétition espacée n'a rien sur quoi s'appliquer"
    )

    # Verrou 2, STATISTIQUE — d'où le nombre de tours. Le tirage est pondéré,
    # donc le ratio est une variable aléatoire. Mesuré sur 200 répétitions à
    # 60 tours : médiane 1,70, écart-type 0,24, mais MINIMUM 1,14 — le seuil de
    # 1,25 tombait dans la queue et rendait ce test rouge ~3 fois sur 100 sans
    # qu'aucun comportement n'ait changé. À 300 tours l'écart-type tombe à 0,09
    # (médiane 1,80, minimum mesuré 1,60 sur 30 essais) : le seuil est à près de
    # six écarts-types, et un échec redevient une information.
    #
    # Une graine fixe aurait aussi supprimé l'aléa, mais elle fige le `random`
    # global que partagent les 600 autres tests, et elle n'aurait vérifié qu'UN
    # tirage — celui-ci en vérifie la loi.
    rounds = 300
    counts: dict[int, int] = {}
    for _ in range(rounds):
        for served in _ids(client, subject="physique", n=10):
            counts[served] = counts.get(served, 0) + 1

    failed_hits = counts.get(qid, 0)
    others = [n for served, n in counts.items() if served != qid]
    average_other = sum(others) / len(others)
    assert failed_hits > average_other * 1.25, (
        f"question ratée servie {failed_hits} fois contre {average_other:.1f} en moyenne"
    )


def test_quiz_serves_the_requested_length_despite_unusable_rows(client):
    """Le filtre « inexploitable » ne doit plus manger la longueur de session.

    Il s'applique APRÈS le `LIMIT` SQL : quand celui-ci valait la longueur
    demandée, chaque ligne écartée raccourcissait le quiz d'autant.
    """
    from db.documents import upsert_document
    from db.questions import save_question

    doc_id = upsert_document(
        path="/tmp/mixte.pdf", filename="mixte.pdf", page_count=40,
        engine="test", has_toc=False, subject="chimie",
    )
    # 10 questions inexploitables (les plus récentes en base) puis 20 bonnes :
    # l'ordre de chargement d'origine les aurait toutes servies en premier.
    for i in range(20):
        save_question(
            doc_id, "page", f"Page {i + 1}", i + 1, i + 1,
            {
                "question": f"Quelle est la notion {i + 1} en chimie ?",
                "question_type": "open",
                "answer": f"Réponse {i + 1}",
                "source_context": f"Le passage {i + 1} explique en détail la notion étudiée.",
            },
        )
    for i in range(10):
        save_question(
            doc_id, "page", f"Page {i + 21}", i + 21, i + 21,
            {"question": "?", "question_type": "open", "answer": "x", "source_context": ""},
        )

    assert len(_ids(client, subject="chimie", n=10)) == 10


def test_interleaved_sessions_also_rotate(client):
    """La pratique entrelacée tire dans le stock, elle ne rejoue pas la même tête."""
    _seed_many("physique", 40)
    _seed_many("histoire", 40)
    first = _ids(client, interleaved=True, n=10)
    second = _ids(client, interleaved=True, n=10)
    assert len(set(first) & set(second)) < 6


def test_the_candidate_pool_is_sampled_not_a_recency_window(client, monkeypatch):
    """Au-delà de la taille du vivier, les questions anciennes restent atteignables.

    Le plafond `QUIZ_SEARCH_POOL` chargeait « les N plus récentes » : passé ce
    seuil, le vieux matériel devenait définitivement introuvable — le même défaut
    que celui corrigé un cran plus haut, simplement déplacé dans le SQL.
    """
    import services.quiz as quiz_service

    monkeypatch.setattr(quiz_service, "QUIZ_SEARCH_POOL", 20)
    _seed_many("physique", 60)  # 3× le vivier

    seen: set[int] = set()
    for _ in range(40):
        seen.update(_ids(client, subject="physique", n=5))
    # Avant : au plus 20 questions distinctes, toujours les 20 plus récentes.
    assert len(seen) > 35, f"seulement {len(seen)} questions atteignables sur 60"


# ── Séance de quiz : réponses gardées, jauges rejouées, profil ───────────────
#
# Un quiz n'avait aucune trace : la séance vivait dans le navigateur, la
# rétention glissait à chaque réponse hors de toute séance, et « Ma progression »
# ne le voyait pas. Il est désormais une séance de pratique, avec sa courbe de
# jauges et ses mouvements de profil, comme une lecture.

def _played(index: int, verdict: str = "correct", question_type: str = "qcm", **extra) -> dict:
    """Une réponse telle que l'écran du quiz l'envoie en fin de séance."""
    return {
        "question_id": None,
        "question": f"Question {index} ?",
        "question_type": question_type,
        "category": "géographie",
        "source": "static",
        "user_answer": "Canberra",
        "verdict": verdict,
        "graded": True,
        "response_time_ms": 3000,
        **extra,
    }


def _record(client, answers, **body) -> int:
    resp = client.post("/api/quiz/session", json={"answers": answers, **body})
    assert resp.status_code == 200
    return resp.json()["session_id"]


def test_an_answer_no_longer_moves_the_profile_on_its_own(client):
    """La rétention glissait de 8 % à CHAQUE réponse, puis encore à la clôture :
    deux modèles de l'apprenant pour une même mesure. Elle passe par la séance."""
    from db.metacog import get_history

    body = client.post("/api/quiz/answer", json={"category": "maths", "correct": True}).json()
    assert body["verdict"] == "correct" and "retention" not in body
    assert get_history() == []


def test_a_recorded_quiz_keeps_its_answers_and_draws_its_gauges(client):
    resp = client.post("/api/quiz/session", json={
        "settings": {"mode": "subject", "subject": "géographie", "topic": "capitales"},
        "answers": [_played(i) for i in range(4)] + [_played(4, "incorrect")],
        "duration_s": 120,
    }).json()
    assert resp["metrics"]["questions_answered"] == 5 and resp["metrics"]["success_rate"] == 80

    detail = client.get(f"/api/progress/practice/{resp['session_id']}").json()
    assert detail["kind"] == "quiz" and detail["completed"] is True
    assert detail["quiz"]["topic"] == "capitales"
    assert [a["verdict"] for a in detail["quiz"]["answers"]] == ["correct"] * 4 + ["incorrect"]
    gauges = detail["gauges"]
    assert gauges["axis"] == "question"
    assert [point["t"] for point in gauges["series"]["retention"]] == [0, 1, 2, 3, 4, 5]
    # Un QCM vise rétention et attention : ce sont elles qui ont bougé. Être juste
    # ne dit rien de la curiosité ni de la créativité.
    assert {"retention", "attention"} <= set(gauges["measured"])
    assert not {"curiosity", "creativity", "meta_cognition"} & set(gauges["measured"])


def test_a_quiz_without_any_answer_is_not_recorded(client):
    body = client.post("/api/quiz/session", json={"answers": [_played(0, verdict="")]}).json()
    assert body["session_id"] is None
    assert client.get("/api/progress/sessions").json()["sessions"] == []


def test_finalizing_a_quiz_moves_the_profile_toward_its_gauges_once(client):
    from db.metacog import ensure_profile, get_history

    sid = _record(client, [_played(i) for i in range(6)], duration_s=90)
    assert client.post("/api/quiz/finalize", json={"session_id": sid}).json()["session_id"] == sid

    profile = ensure_profile()
    assert float(profile["retention"]) > 50.0
    # Ni la curiosité ni la créativité : six QCM ne les ont pas mesurées.
    assert float(profile["curiosity"]) == 50.0 and float(profile["creativity"]) == 50.0
    rows = [row for row in get_history() if row["practice_session_id"] == sid]
    assert rows and all(row["session_id"] is None for row in rows)

    # Quitter puis clore, ou une clôture renvoyée : le profil ne glisse qu'une fois.
    client.post("/api/quiz/finalize", json={"session_id": sid})
    again = ensure_profile()
    assert float(again["retention"]) == float(profile["retention"])
    assert int(again["sessions_count"]) == 1


def test_wrong_answers_pull_the_session_gauges_below_their_seed(client):
    sid = _record(client, [_played(i, "incorrect") for i in range(5)])
    gauges = client.get(f"/api/progress/practice/{sid}").json()["gauges"]
    assert gauges["series"]["retention"][-1]["value"] < gauges["seed"]["retention"]


def test_finalizing_an_unknown_quiz_session_is_a_404(client):
    assert client.post("/api/quiz/finalize", json={"session_id": 424242}).status_code == 404


def test_a_written_answer_moves_the_gauges_with_its_llm_signals(client):
    """Corrigée par le LLM, une réponse rédigée garde ses signaux : la curiosité
    bouge comme dans le lecteur — ce qu'un verdict seul ne fait jamais."""
    signals = {"metacog_signals": {"curiosity": 2.0}, "curiosity_signals": {}, "creativity_signals": {}}
    sid = _record(client, [_played(
        0, question_type="curiosity", user_answer="Et si la Lune n'existait pas ?", signals=signals,
    )])
    assert "curiosity" in client.get(f"/api/progress/practice/{sid}").json()["gauges"]["measured"]


def test_evaluate_hands_back_only_the_signals_the_engine_can_read(client, monkeypatch):
    evaluator, _seen = _evaluator(
        "correct", metacog_signals={"curiosity": 1.5, "attention": 9, "inconnu": 1, "retention": "x"},
    )
    monkeypatch.setattr("services.quiz.evaluate_answer_async", evaluator)
    qid = _seed_typed_question("teach_back", subject="chimie")

    body = client.post("/api/quiz/evaluate", json={"question_id": qid, "user_answer": "Mon explication."}).json()
    assert body["signals"]["metacog_signals"] == {"curiosity": 1.5, "attention": 2.0}

    choices = ["La réponse attendue", "Faux A", "Faux B", "Faux C"]
    qcm = _seed_typed_question("qcm", choices=choices, subject="physique")
    body = client.post("/api/quiz/evaluate", json={"question_id": qcm, "user_answer": "Faux A"}).json()
    assert body["signals"] is None  # verdict objectif : aucun signal à inventer


def test_the_quiz_debrief_is_kept_with_its_session(client, monkeypatch):
    def _analysis(context, on_success, on_error, model=None):
        on_success({"analysis": "Tu maîtrises les capitales européennes."})

    monkeypatch.setattr("services.quiz.generate_quiz_session_analysis_async", _analysis)
    sid = _record(client, [_played(0)])
    client.post("/api/quiz/analysis", json={
        "answers": [{"question": "Question 0 ?", "verdict": "correct", "category": "géographie"}],
        "session_id": sid,
    })
    assert client.get(f"/api/progress/practice/{sid}").json()["analysis"] == (
        "Tu maîtrises les capitales européennes."
    )


def test_one_written_answer_among_qcm_does_not_drag_the_profile_down(client):
    """Une réponse rédigée au milieu de QCM : le modèle du lecteur aurait poussé
    la curiosité et la métacognition d'un cheveu au-dessus de leur amorce
    (profil × 0,8)… et le profil serait descendu vers elles. Ce qu'une mesure
    n'informe pas ne bouge pas ; ce qu'elle informe une fois pèse pour une fois."""
    from db.metacog import ensure_profile

    signals = {"metacog_signals": {"curiosity": 0.4}, "curiosity_signals": {}, "creativity_signals": {}}
    sid = _record(client, [_played(i) for i in range(4)] + [
        _played(4, question_type="comprehension", user_answer="Le texte décrit trois étapes.", signals=signals),
    ])
    client.post("/api/quiz/finalize", json={"session_id": sid})
    profile = ensure_profile()
    assert float(profile["meta_cognition"]) == 50.0
    assert float(profile["creativity"]) == 50.0
    # La curiosité, relevée une fois, ne pèse qu'un quart : elle bouge, peu.
    assert abs(float(profile["curiosity"]) - 50.0) < abs(float(profile["retention"]) - 50.0)
