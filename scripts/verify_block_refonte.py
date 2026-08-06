#!/usr/bin/env python3
"""Vérification de la refonte scroll libre + bulle assistant (branche block).

Teste sans UI : migration DB v17, échanges assistant, stats de session,
mémoire de session, politique d'intervention, parsers et prompts LLM,
page_sizes PyMuPDF, et imports des modules UI.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "nwol"))

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "ok" if condition else "ÉCHEC"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="nwol_verif_"))

    # ── 1. Migration de la vraie DB (copie) vers v17 ─────────────────────
    import db as db_module
    real_db = ROOT / "data" / "nwol.db"
    test_db = tmp / "nwol.db"
    if real_db.exists():
        shutil.copy(real_db, test_db)
    db_module.DB_PATH = str(test_db)

    from db.schema import initialize_schema
    initialize_schema()
    conn = db_module.get_connection()
    version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    check("schema_version == 18", version == 18, f"version={version}")
    user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(user)")}
    check("colonnes user assistant", {"assistant_mode", "bubble_rel_x", "bubble_rel_y"} <= user_cols)

    # ── 2. Préférences assistant ─────────────────────────────────────────
    from db.user import (DEFAULT_USER_ID, ensure_default_user, get_assistant_prefs,
                         save_assistant_mode, save_bubble_position)
    ensure_default_user()
    prefs = get_assistant_prefs()
    check("mode par défaut normal", prefs["mode"] == "normal", str(prefs))
    save_assistant_mode(DEFAULT_USER_ID, "coach")
    save_bubble_position(DEFAULT_USER_ID, 0.42, 1.7)  # clampé à 1.0
    prefs = get_assistant_prefs()
    check("mode coach persistant", prefs["mode"] == "coach")
    check("position bulle clampée", prefs["bubble_rel_x"] == 0.42 and prefs["bubble_rel_y"] == 1.0)
    save_assistant_mode(DEFAULT_USER_ID, "normal")

    # ── 3. Échanges assistant + stats ────────────────────────────────────
    from db.documents import upsert_document
    from db.questions import (count_assistant_questions, get_assistant_help_pages,
                              save_assistant_exchange)
    from db.sessions import get_session
    from metacog.session import SessionManager

    doc_id = upsert_document(str(tmp / "fake.pdf"), "fake.pdf", 30, "pymupdf_scroll", False)
    mgr = SessionManager(doc_id)
    sid = mgr.session_id
    qid = save_assistant_exchange(doc_id, 7, "Pourquoi softmax ?", "Parce que…", session_id=sid)
    save_assistant_exchange(doc_id, 7, "Et la température ?", "Elle adoucit…", session_id=sid)
    save_assistant_exchange(doc_id, 12, "C'est quoi un head ?", "Une projection…", session_id=sid)
    check("save_assistant_exchange retourne un id", isinstance(qid, int) and qid > 0)
    row = conn.execute("SELECT scope_type, question_type, page_start, page_end, answer FROM questions WHERE id=?", (qid,)).fetchone()
    check("ligne questions assistant_follow_up",
          row["scope_type"] == "assistant_follow_up" and row["question_type"] == "open"
          and row["page_start"] == 7 and row["page_end"] == 7 and row["answer"] == "Parce que…")
    n_answers = conn.execute("SELECT COUNT(*) FROM answers WHERE question_id=?", (qid,)).fetchone()[0]
    check("aucune ligne answers pour question libre", n_answers == 0)
    check("count_assistant_questions == 3", count_assistant_questions(sid) == 3)
    help_pages = get_assistant_help_pages(sid)
    check("help_pages triées", help_pages and help_pages[0] == {"page": 7, "questions_count": 2}, str(help_pages))

    # Jauges depuis signaux follow-up (verdict None, pas de subject)
    before = mgr.current_gauges()["curiosity"]
    mgr.update_from_evaluation({
        "verdict": None,
        "metacog_signals": {"curiosity": 1.2, "attention": 0.4},
        "follow_up_answer": "réponse",
    })
    after = mgr.current_gauges()["curiosity"]
    check("jauge curiosité montée par follow-up", after > before, f"{before} → {after}")

    summary = mgr.end_session(pages_read=14, chapters_completed=[])
    check("summary assistant_questions", summary.get("assistant_questions") == 3, str(summary.get("assistant_questions")))
    check("summary help_pages", summary.get("help_pages") == help_pages)
    check("pages_read enregistré", get_session(sid)["pages_read"] == 14)

    # ── 4. ReaderState ───────────────────────────────────────────────────
    from reader.state import ReaderState
    state = ReaderState(doc_id=doc_id, total_pages=30)
    for p in (1, 2, 3, 2, 9):
        state.mark_page_seen(p)
    check("pages_read_count = pages distinctes vues", state.pages_read_count() == 4)
    check("current_page = dernière dominante", state.current_page == 9)

    # ── 5. SessionMemory ─────────────────────────────────────────────────
    from reader.session_memory import SessionMemory
    memory = SessionMemory()
    t0 = 1000.0
    memory.on_page_view(1, t0)
    memory.on_page_view(2, t0 + 10)
    memory.on_page_view(1, t0 + 25)   # retour page 1
    memory.on_user_question(1, "q1")
    memory.on_user_question(1, "q2")
    memory.on_user_question(2, "q3")
    check("dwell page 1 cumulé", abs(memory.dwell_by_page[1] - 10.0) < 0.01, str(memory.dwell_by_page))
    check("visites page 1 == 2", memory.visits(1) == 2)
    check("dwell courant", abs(memory.current_dwell(t0 + 40) - 15.0) < 0.01)
    check("help_pages mémoire", memory.help_pages()[0] == {"page": 1, "questions_count": 2})

    # ── 6. Politique d'intervention ──────────────────────────────────────
    from reader.intervention import AssistantInterventionPolicy, _is_math_heavy
    decisions: list[dict] = []
    requests: list[dict] = []

    def fake_request(context, on_done):
        requests.append(context)
        on_done({"should_intervene": True, "kind": "offer_help", "message": "Je peux aider.", "question": ""})

    mem2 = SessionMemory()
    mem2.on_page_view(5, time.monotonic() - 200)  # 200 s sur la page 5
    policy = AssistantInterventionPolicy(
        memory=mem2,
        get_mode=lambda: "normal",
        get_gauges=lambda: {"attention": 80.0},
        get_current_page=lambda: 5,
        get_page_text=lambda p: "texte " * 100,
        request_decision=fake_request,
        on_intervention=decisions.append,
    )
    policy.tick()
    check("long_dwell déclenche", len(requests) == 1 and requests[0]["trigger"] == "long_dwell", str(requests))
    check("intervention transmise", len(decisions) == 1 and decisions[0]["kind"] == "offer_help" and decisions[0]["page"] == 5)
    policy.tick()
    check("cooldown global bloque", len(requests) == 1)

    # mode discret : jamais d'intervention
    mem3 = SessionMemory()
    mem3.on_page_view(3, time.monotonic() - 500)
    silent = AssistantInterventionPolicy(
        memory=mem3, get_mode=lambda: "discret", get_gauges=lambda: {},
        get_current_page=lambda: 3, get_page_text=lambda p: "x" * 500,
        request_decision=lambda c, cb: FAILURES.append("discret a déclenché"),
        on_intervention=lambda d: FAILURES.append("discret a transmis"),
    )
    silent.tick()
    check("mode discret silencieux", True)

    check("détection page math", _is_math_heavy("∑ x_i = ∫ f(x) dx " * 30) and not _is_math_heavy("plain words " * 50))

    # ── 7. Parsers LLM ───────────────────────────────────────────────────
    from llm.schema_json import parse_follow_up, parse_intervention
    parsed = parse_intervention('{"should_intervene": true, "kind": "ask_question", "message": "Petit défi ?", "question": "Quelle est l\'idée clé ?"}')
    check("parse_intervention nominal", parsed == {
        "should_intervene": True, "kind": "ask_question",
        "message": "Petit défi ?", "question": "Quelle est l'idée clé ?",
    }, str(parsed))
    parsed = parse_intervention('{"should_intervene": "oui", "kind": "danse", "message": "", "question": ""}')
    check("parse_intervention contenu vide → silence", parsed["should_intervene"] is False and parsed["kind"] == "offer_help")
    parsed = parse_intervention('{"should_intervene": false}')
    check("parse_intervention refus", parsed["should_intervene"] is False)
    check("parse_intervention rejette non-dict", parse_intervention("pas du json") is None)
    fu = parse_follow_up('{"answer": "Réponse claire.", "metacog_signals": {"curiosity": 0.2}}')
    check("parse_follow_up curiosity >= 1", fu["metacog_signals"]["curiosity"] >= 1.0)

    # ── 8. Prompts ───────────────────────────────────────────────────────
    from llm.prompts import build_assistant_answer_prompt, build_intervention_prompt
    prompt = build_assistant_answer_prompt(
        page_text="La couche d'attention calcule…",
        user_question="Pourquoi diviser par √d ?",
        doc_title="Attention.pdf", chapter_title="3. Architecture", page_number=4,
        metacog_profile={"curiosity": 60}, session_gauges={"attention": 55},
        recent_exchanges=[{"question": "q?", "answer": "r."}],
    )
    check("prompt assistant : sections follow_up partagées",
          "Paragraphe source" in prompt and "Question de l'étudiant" in prompt
          and "page visible : 4" in prompt)
    iprompt = build_intervention_prompt({
        "trigger": "hard_page", "page": 9, "page_text": "∑ formules",
        "gauges": {"attention": 35}, "dwell_s": 120, "visits": 1,
        "user_questions_on_page": 0, "mode": "coach",
    })
    check("prompt intervention", "should_intervene" in iprompt and "rephrase_offer" in iprompt and "page 9" in iprompt)

    # ── 9. Fallbacks ollama_client ───────────────────────────────────────
    from llm.ollama_client import _fallback_json_result
    fb = _fallback_json_result("assistant_intervention", iprompt, parse_intervention)
    check("fallback intervention silencieux", fb is not None and fb["should_intervene"] is False)
    fb = _fallback_json_result("assistant_answer", prompt, parse_follow_up)
    check("fallback assistant_answer répond", fb is not None and bool(fb.get("answer")))

    # ── 10. PyMuPDF page_sizes ───────────────────────────────────────────
    from pdf_viewer.pdf_document import PdfDocument
    # Aucun PDF n'est versionné : NWOL_TEST_PDF pointe le sien (sinon on saute).
    pdf = Path(os.environ.get("NWOL_TEST_PDF", ""))
    if str(pdf) and pdf.exists():
        with PdfDocument(str(pdf)) as doc:
            sizes = doc.page_sizes()
            check("page_sizes complet", len(sizes) == doc.page_count() and all(w > 0 and h > 0 for w, h in sizes))
    else:
        print("[skip] PDF de test absent")

    # ── 11. Snapshot ─────────────────────────────────────────────────────
    from reader.context_snapshot import make_snapshot
    snap = make_snapshot(3, "texte", None, doc_id, "doc.pdf", "Chap 1",
                         gauges={"attention": 50}, history=[{"q": i} for i in range(9)])
    check("snapshot id + historique limité", len(snap.snapshot_id) == 12 and len(snap.history) == 5 and snap.page_number == 3)

    # ── 12. Imports UI (sans instanciation Tk) ───────────────────────────
    import ui.assistant_bubble  # noqa: F401
    import ui.scroll_reader  # noqa: F401
    import ui.app  # noqa: F401
    check("imports UI", True)

    db_module.close_connection()
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} échec(s) : {FAILURES}")
        return 1
    print("Tous les contrôles passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
