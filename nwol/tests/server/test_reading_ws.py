def _relax_policy(monkeypatch, *, dwell=0.0, cooldown=0.0, warmup=0.0, page_cooldown=0.0):
    """Neutralise la cadence de la politique d'intervention pour un test.

    Les seuils sont importés dans `services.intervention` au chargement du module :
    c'est là qu'il faut les remplacer, pas dans `config.settings`."""
    from services import intervention

    modes = ("discret", "normal", "coach")
    monkeypatch.setattr(intervention, "ASSISTANT_DWELL_TRIGGER_S", dict.fromkeys(modes, dwell))
    monkeypatch.setattr(intervention, "ASSISTANT_GLOBAL_COOLDOWN", dict.fromkeys(modes, cooldown))
    monkeypatch.setattr(intervention, "ASSISTANT_PAGE_COOLDOWN", dict.fromkeys(modes, page_cooldown))
    monkeypatch.setattr(intervention, "ASSISTANT_WARMUP_S", dict.fromkeys(modes, warmup))


def test_build_answer_context_empty_db(client):
    # Pas de document -> contexte avec valeurs par défaut sûres.
    from services.assistant import build_answer_context

    ctx = build_answer_context(doc_id=1, page=2, question="Pourquoi ?")
    assert ctx["user_question"] == "Pourquoi ?"
    assert ctx["page_number"] == 2
    assert ctx["page_text"] == ""
    assert ctx["doc_title"] == ""
    assert ctx["chapter_title"] == ""
    # Pas de document -> pas d'image attachée (vision dégrade gracieusement).
    assert ctx["image_paths"] == []


def test_reader_websocket_answer(client, monkeypatch):
    # answerer factice : pas d'Ollama, on_success synchrone.
    from services import assistant

    def fake_answer(doc_id, page, question, on_success, on_error, **_kw):
        on_success({"answer": f"Réponse à : {question}", "highlights": [{"quote": "x", "purpose": "key"}]})

    monkeypatch.setattr(assistant, "answer_question", fake_answer)

    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "ask", "question": "C'est quoi X ?", "page": 3})
        first = ws.receive_json()
        assert first["type"] == "loading"
        second = ws.receive_json()
        assert second["type"] == "answer"
        assert "C'est quoi X ?" in second["answer"]
        assert second["highlights"][0]["purpose"] == "key"


def test_reader_websocket_viewport_then_ask(client, monkeypatch):
    from services import assistant

    monkeypatch.setattr(
        assistant, "answer_question",
        lambda d, p, q, ok, err, **kw: ok({"answer": "ok", "highlights": []}),
    )

    with client.websocket_connect("/api/reader/1/stream") as ws:
        # Le message viewport ne doit pas perturber le protocole.
        ws.send_json({"type": "viewport", "page": 5})
        ws.send_json({"type": "ask", "question": "test", "page": 5})
        assert ws.receive_json()["type"] == "loading"
        assert ws.receive_json()["type"] == "answer"


def test_reader_ws_rephrase(client, monkeypatch):
    from services import assistant

    monkeypatch.setattr(
        assistant, "rephrase_page",
        lambda d, p, ok, err, **kw: ok({"answer": "reformulé", "highlights": []}),
    )
    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "rephrase", "page": 2})
        assert ws.receive_json()["type"] == "loading"
        a = ws.receive_json()
        assert a["type"] == "answer" and a["answer"] == "reformulé"


def test_reader_ws_mode_and_focus(client):
    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "mode", "mode": "coach"})
        m = ws.receive_json()
        assert m["type"] == "system" and "coach" in m["message"]

        ws.send_json({"type": "focus"})
        f = ws.receive_json()
        assert f["type"] == "system" and "focus" in f["message"].lower()


def test_rephrase_service_wraps_output(client):
    from services import assistant

    captured: dict = {}

    def fake_gen(ctx, ok, err):
        captured["ctx"] = ctx
        ok({"rephrased_paragraph": "Texte simplifié", "note": "plus clair", "highlights": []})

    out: dict = {}
    assistant.rephrase_page(1, 1, lambda r: out.update(r), lambda m: None, generator=fake_gen)
    assert "Texte simplifié" in out["answer"]
    assert "plus clair" in out["answer"]
    assert "paragraph" in captured["ctx"]


def test_reader_ws_guided_qa(client, monkeypatch):
    from services import assistant

    monkeypatch.setattr(
        assistant, "generate_page_question",
        lambda d, p, ok, err, **kw: ok({"question": "Quelle est la thèse ?", "choices": None, "question_type": "open"}),
    )
    monkeypatch.setattr(
        assistant, "evaluate_page_answer",
        lambda d, p, q, a, ok, err, **kw: ok({
            "verdict": "correct", "feedback": "Bien vu.",
            "highlights": [{"quote": "la thèse centrale", "purpose": "key"}],
        }),
    )

    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "start_qa", "page": 1})
        assert ws.receive_json()["type"] == "loading"
        q = ws.receive_json()
        assert q["type"] == "qa_question" and "thèse" in q["question"]

        ws.send_json({"type": "qa_answer", "question": q["question"], "answer": "La thèse est X", "page": 1})
        assert ws.receive_json()["type"] == "loading"
        fb = ws.receive_json()
        assert fb["type"] == "qa_feedback" and fb["verdict"] == "correct" and fb["feedback"] == "Bien vu."
        # Le feedback d'évaluation transporte ses surlignages justificatifs.
        assert fb["highlights"][0]["purpose"] == "key"


def test_page_question_and_eval_context(client):
    from services import assistant

    cap: dict = {}
    assistant.generate_page_question(1, 1, lambda r: None, lambda m: None, generator=lambda ctx, ok, err: cap.update(q=ctx))
    assert "paragraph" in cap["q"] and cap["q"]["standalone"] is True

    assistant.evaluate_page_answer(
        1, 1, "Q ?", "A", lambda r: None, lambda m: None,
        question_type="ordering",
        evaluator=lambda ctx, ok, err: cap.update(e=ctx),
    )
    # Le type accompagne la question : il conditionne la consigne de correction.
    assert cap["e"]["user_answer"] == "A"
    assert cap["e"]["question"] == {"question": "Q ?", "question_type": "ordering"}


def test_reader_websocket_error(client, monkeypatch):
    from services import assistant

    def fake_answer(doc_id, page, question, on_success, on_error, **_kw):
        on_error("Ollama indisponible")

    monkeypatch.setattr(assistant, "answer_question", fake_answer)

    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "ask", "question": "test", "page": 1})
        assert ws.receive_json()["type"] == "loading"
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "Ollama" in err["message"]


def test_live_gauges_seed_and_apply(client):
    # Seed = profil long terme (50) × 0.8 = 40 ; les signaux font bouger la jauge.
    from services.session import LiveGauges

    lg = LiveGauges()
    snap = lg.snapshot()
    assert abs(snap["attention"] - 40.0) < 1e-6
    after = lg.apply({"verdict": "correct", "metacog_signals": {"attention": 1.0}})
    assert after["attention"] > snap["attention"]


def test_intervention_context_relays_policy_trigger(client):
    # build_intervention_context ne DÉCIDE plus rien : il relaie le signal que la
    # politique (services/intervention.py) lui passe. Garde-fou anti-duplication.
    from services import assistant

    ctx = assistant.build_intervention_context(
        1, 1, trigger="low_attention", dwell_s=70.0, visits=1, questions_on_page=0,
        mode="normal", gauges={"attention": 10.0},
    )
    assert ctx["trigger"] == "low_attention"
    assert ctx["gauges"]["attention"] == 10.0


def test_reader_ws_threads_session_gauges(client, monkeypatch):
    # Les jauges live (seedées au connect) doivent être injectées dans le contexte Q&A.
    from services import assistant

    captured: dict = {}

    def fake_answer(doc_id, page, question, on_success, on_error, **kw):
        captured.update(kw)
        on_success({"answer": "ok", "highlights": []})

    monkeypatch.setattr(assistant, "answer_question", fake_answer)

    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "ask", "question": "Q", "page": 1})
        assert ws.receive_json()["type"] == "loading"
        assert ws.receive_json()["type"] == "answer"

    gauges = captured.get("session_gauges") or {}
    assert "attention" in gauges and 0.0 <= gauges["attention"] <= 100.0
    assert "recent_exchanges" in captured


def test_reader_ws_persists_free_qa(client, monkeypatch):
    # Une question libre + sa réponse sont enregistrées (scope assistant_follow_up).
    from db.documents import upsert_document
    from db.questions import get_questions_for_scope
    from services import assistant

    doc_id = upsert_document("/tmp/persist_qa.pdf", "persist_qa.pdf", 10, "pymupdf", False)

    monkeypatch.setattr(
        assistant, "answer_question",
        lambda d, p, q, ok, err, **kw: ok({"answer": "Réponse persistée", "highlights": []}),
    )

    with client.websocket_connect(f"/api/reader/{doc_id}/stream") as ws:
        ws.send_json({"type": "ask", "question": "Pourquoi le ciel est bleu ?", "page": 4})
        assert ws.receive_json()["type"] == "loading"
        assert ws.receive_json()["type"] == "answer"

    saved = [r for r in get_questions_for_scope(doc_id, 4, 4) if r["scope_type"] == "assistant_follow_up"]
    assert saved and saved[0]["question"] == "Pourquoi le ciel est bleu ?"
    assert saved[0]["answer"] == "Réponse persistée"


def test_reader_ws_forwards_selected_snippets(client, monkeypatch):
    # Les extraits ajoutés au contexte sont nettoyés puis transmis à l'assistant.
    from services import assistant

    captured: dict = {}

    def fake_answer(doc_id, page, question, on_success, on_error, **kw):
        captured.update(kw)
        on_success({"answer": "ok", "highlights": []})

    monkeypatch.setattr(assistant, "answer_question", fake_answer)

    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({
            "type": "ask", "question": "Q", "page": 1,
            "selected_snippets": ["  extrait A ", "", "extrait B"],
        })
        assert ws.receive_json()["type"] == "loading"
        assert ws.receive_json()["type"] == "answer"

    assert captured.get("selected_snippets") == ["extrait A", "extrait B"]


def test_reader_ws_qa_creates_auto_flashcard(client, monkeypatch):
    # Bonne réponse + flashcard du LLM -> carte 'auto' persistée + flag UI.
    from db.documents import upsert_document
    from db.flashcards import get_flashcards
    from services import assistant

    doc_id = upsert_document("/tmp/fc_auto.pdf", "fc_auto.pdf", 5, "pymupdf", False)

    monkeypatch.setattr(
        assistant, "generate_page_question",
        lambda d, p, ok, err, **kw: ok({"question": "Q ?", "choices": None, "question_type": "comprehension"}),
    )
    monkeypatch.setattr(
        assistant, "evaluate_page_answer",
        lambda d, p, q, a, ok, err, **kw: ok({
            "verdict": "correct", "feedback": "ok",
            "flashcard": {"front": "Définition de X ?", "back": "X est ...", "tags": ["x"], "difficulty": 2},
        }),
    )

    with client.websocket_connect(f"/api/reader/{doc_id}/stream") as ws:
        ws.send_json({"type": "start_qa", "page": 1})
        assert ws.receive_json()["type"] == "loading"
        q = ws.receive_json()
        assert q["type"] == "qa_question"
        ws.send_json({"type": "qa_answer", "question": q["question"], "answer": "X est ...", "page": 1})
        assert ws.receive_json()["type"] == "loading"
        fb = ws.receive_json()
        assert fb["type"] == "qa_feedback"
        assert fb["flashcard_created"] is True

    cards = get_flashcards(document_id=doc_id)
    assert any(c["source"] == "auto" and c["front"] == "Définition de X ?" for c in cards)


def test_reader_ws_gated_question_from_intervention(client, monkeypatch):
    # Une décision d'intervention "ask_question" devient une question BLOQUANTE.
    from server.routers import reading
    from services import assistant

    monkeypatch.setattr(reading, "_TICK_SECONDS", 0.05)
    _relax_policy(monkeypatch, dwell=0.0, cooldown=0.0, warmup=0.0)
    monkeypatch.setattr(
        assistant, "build_intervention_context",
        lambda *a, **k: {"trigger": "long_dwell", "page": 1},
    )
    monkeypatch.setattr(
        reading, "decide_intervention_async",
        lambda ctx, ok, err, **kw: ok({"should_intervene": True, "kind": "ask_question"}),
    )
    monkeypatch.setattr(
        assistant, "generate_page_question",
        lambda d, p, ok, err, **kw: ok({"question": "Idée clé ?", "choices": None, "question_type": "comprehension"}),
    )

    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "mode", "mode": "coach"})
        assert ws.receive_json()["type"] == "system"
        # Le ticker doit finir par émettre une question bloquante.
        evt = None
        for _ in range(20):
            evt = ws.receive_json()
            if evt["type"] == "gated_question":
                break
        assert evt["type"] == "gated_question"
        assert evt["page"] == 1
        assert "clé" in evt["question"]


def test_reader_ws_warmup_silences_start_of_reading(client, monkeypatch):
    # Début de lecture : même dwell/cooldown à zéro, le warm-up tient Gemma silencieuse.
    import time

    from server.routers import reading
    from services import assistant

    decided = []
    monkeypatch.setattr(reading, "_TICK_SECONDS", 0.01)
    _relax_policy(monkeypatch, dwell=0.0, cooldown=0.0, warmup=60.0)
    monkeypatch.setattr(
        assistant, "build_intervention_context",
        lambda *a, **k: decided.append(1) or {"trigger": "long_dwell", "page": 1},
    )

    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "viewport", "page": 1})
        time.sleep(0.2)  # plusieurs ticks : tous doivent tomber dans le warm-up
    assert decided == []


def test_type_aware_gauges_differentiate(client):
    # Une question de curiosité fait surtout bouger `curiosity`, pas `context`.
    from metacog.gauges import make_gauges, update_gauges_from_evaluation

    gauges = make_gauges({})
    before = {k: v.value for k, v in gauges.items()}
    update_gauges_from_evaluation(gauges, {
        "verdict": "correct",
        "question_type": "curiosity",
        "metacog_signals": {"curiosity": 1.0, "context_comprehension": 1.0},
    })
    d_cur = gauges["curiosity"].value - before["curiosity"]
    d_ctx = gauges["context_comprehension"].value - before["context_comprehension"]
    assert d_cur > d_ctx


def test_reader_ws_recall_sends_the_passage_to_hide(client, monkeypatch):
    """Rappel libre : le client reçoit la CITATION à cacher, pas des indices de
    caractères — c'est une citation que sait localiser le lecteur (search_page)."""
    from services import assistant, library

    page = "Le théorème de Rolle affirme qu'entre deux zéros d'une fonction dérivable, la dérivée s'annule."
    monkeypatch.setattr(library, "page_text", lambda doc_id, p: page)
    monkeypatch.setattr(
        assistant, "generate_page_question",
        lambda d, p, ok, err, **kw: ok({
            "question": "Redonne l'énoncé masqué.",
            "choices": None,
            "question_type": "recall",
            "expected_answer": "La dérivée s'annule entre deux zéros.",
            "paragraph_mask": {
                "enabled": True,
                "start_char": 0,
                "end_char": 96,
                "placeholder": "énoncé masqué",
            },
        }),
    )

    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "start_qa", "page": 1})
        assert ws.receive_json()["type"] == "loading"
        q = ws.receive_json()
        assert q["type"] == "qa_question" and q["question_type"] == "recall"
        assert q["mask"]["quote"].startswith("Le théorème de Rolle")
        assert q["mask"]["placeholder"] == "énoncé masqué"


def test_reader_ws_question_without_mask_says_so(client, monkeypatch):
    """Sans masque, le champ vaut null : le lecteur ne cache rien."""
    from services import assistant

    monkeypatch.setattr(
        assistant, "generate_page_question",
        lambda d, p, ok, err, **kw: ok({"question": "Idée clé ?", "choices": None, "question_type": "open"}),
    )

    with client.websocket_connect("/api/reader/1/stream") as ws:
        ws.send_json({"type": "start_qa", "page": 1})
        assert ws.receive_json()["type"] == "loading"
        assert ws.receive_json()["mask"] is None


# ── Correction : ce qui se juge tout seul ne passe plus par le LLM ──────────

def _seed_question(monkeypatch, question_type: str, answer: str, choices=None) -> int:
    """Question persistée + page factice (aucun PDF réel derrière ces tests)."""
    from db.documents import upsert_document
    from db.questions import save_question
    from services import library

    doc_id = upsert_document(
        path=f"/tmp/eval-{question_type}.pdf", filename="eval.pdf", page_count=2,
        engine="test", has_toc=False,
    )
    monkeypatch.setattr(library, "page_text", lambda d, p: "Le paragraphe source.")
    return save_question(
        doc_id, "page", "Page 1", 1, 1,
        {"question": "La question ?", "question_type": question_type,
         "choices": choices, "answer": answer},
    )


def test_evaluation_receives_the_stored_answer_and_choices(client, monkeypatch):
    """Le LLM corrigeait sans voir la réponse attendue : il la redéduisait de la page."""
    from services import assistant

    qid = _seed_question(monkeypatch, "qcm", "12 m/s", ["3 m/s", "12 m/s", "30 m/s"])
    cap: dict = {}
    assistant.evaluate_page_answer(
        1, 1, "La question ?", "12 m/s", lambda r: None, lambda m: None,
        question_type="qcm", question_id=qid,
        evaluator=lambda ctx, ok, err: cap.update(ctx=ctx),
    )
    assert cap["ctx"]["question"]["expected_answer"] == "12 m/s"
    assert cap["ctx"]["question"]["choices"] == ["3 m/s", "12 m/s", "30 m/s"]
    assert cap["ctx"]["objective_verdict"] == "correct"


def test_wrong_qcm_choice_stays_wrong_even_if_the_llm_says_otherwise(client, monkeypatch):
    """Une hallucination ne doit pas pouvoir valider un mauvais choix."""
    from services import assistant

    qid = _seed_question(monkeypatch, "qcm", "12 m/s", ["3 m/s", "12 m/s", "30 m/s"])
    out: dict = {}
    assistant.evaluate_page_answer(
        1, 1, "La question ?", "3 m/s", lambda r: out.update(r), lambda m: None,
        question_type="qcm", question_id=qid,
        evaluator=lambda ctx, ok, err: ok({"verdict": "correct", "feedback": "Bravo !", "hint": ""}),
    )
    assert out["verdict"] == "incorrect"


def test_ordering_verdict_is_computed_from_the_stored_steps(client, monkeypatch):
    from services import assistant

    steps = ["Poser les hypothèses", "Appliquer le théorème", "Conclure"]
    qid = _seed_question(monkeypatch, "ordering", "1. Poser 2. Appliquer 3. Conclure", steps)

    def _evaluate(answer: str) -> str:
        out: dict = {}
        assistant.evaluate_page_answer(
            1, 1, "La question ?", answer, lambda r: out.update(r), lambda m: None,
            question_type="ordering", question_id=qid,
            evaluator=lambda ctx, ok, err: ok({"verdict": "correct", "feedback": "…", "completion": "x"}),
        )
        return out["verdict"]

    assert _evaluate("1. Poser les hypothèses\n2. Appliquer le théorème\n3. Conclure") == "correct"
    # Deux étapes voisines permutées : la séquence est comprise, l'ordre non.
    assert _evaluate("1. Appliquer le théorème\n2. Poser les hypothèses\n3. Conclure") == "partial"
    assert _evaluate("1. Conclure\n2. Poser les hypothèses\n3. Appliquer le théorème") == "incorrect"


def test_open_types_keep_the_llm_verdict(client, monkeypatch):
    """Là où il y a un jugement à porter, c'est le LLM qui tranche — inchangé."""
    from services import assistant

    qid = _seed_question(monkeypatch, "teach_back", "Une explication simple")
    out: dict = {}
    assistant.evaluate_page_answer(
        1, 1, "La question ?", "Mon explication", lambda r: out.update(r), lambda m: None,
        question_type="teach_back", question_id=qid,
        evaluator=lambda ctx, ok, err: ok({"verdict": "partial", "feedback": "…", "completion": "précise"}),
    )
    assert out["verdict"] == "partial" and out["completion"] == "précise"
