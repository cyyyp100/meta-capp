# scripts/test_lot_abc.py — Vérification hors-UI des lots A/B/C sur une COPIE de la base
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "nwol"))

# Base de test : copie de la vraie base si présente, sinon base vierge.
tmp_db = Path(tempfile.mkdtemp()) / "nwol_test.db"
real_db = ROOT / "data" / "nwol.db"
if real_db.exists():
    shutil.copy(real_db, tmp_db)
    print(f"[setup] copie de {real_db} -> {tmp_db}")
else:
    print("[setup] pas de base existante : base vierge")

import db  # noqa: E402

db.DB_PATH = str(tmp_db)

from db.schema import initialize_schema  # noqa: E402

initialize_schema()

conn = db.get_connection()
version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
assert version == 19, f"version schéma attendue 19, obtenue {version}"
print(f"[B1] schéma v{version} OK")

cols = {row["name"] for row in conn.execute("PRAGMA table_info(flashcards)")}
assert {"due_at", "interval_days"} <= cols, cols
tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert "page_dwell" in tables
print("[B1] colonnes due_at/interval_days + table page_dwell OK")

# ── B2 : SR flashcards ────────────────────────────────────────────────────────
from db.flashcards import (  # noqa: E402
    get_due_flashcards,
    get_related_flashcards,
    get_session_start_cards,
    save_flashcard,
    update_review,
)

card_id = save_flashcard(
    user_id=1, question_id=None, front="Question test SR ?", back="Réponse test.",
    tags=["test"], difficulty=2, source="manual",
)
row = conn.execute("SELECT due_at, interval_days FROM flashcards WHERE id=?", (card_id,)).fetchone()
assert row["interval_days"] == 1.0 and row["due_at"], dict(row)
print(f"[B2] save_flashcard : due_at={row['due_at']} interval={row['interval_days']}")

update_review(card_id, "correct")
row = conn.execute("SELECT interval_days, review_count, last_verdict FROM flashcards WHERE id=?", (card_id,)).fetchone()
assert abs(row["interval_days"] - 2.5) < 1e-6, dict(row)
update_review(card_id, "partial")
row = conn.execute("SELECT interval_days FROM flashcards WHERE id=?", (card_id,)).fetchone()
assert abs(row["interval_days"] - 3.0) < 1e-6, dict(row)
update_review(card_id, "incorrect")
row = conn.execute("SELECT interval_days FROM flashcards WHERE id=?", (card_id,)).fetchone()
assert row["interval_days"] == 1.0, dict(row)
print("[B2] update_review SR : 1.0 → ×2.5 → ×1.2 → reset OK")

# Carte due : forcer l'échéance dans le passé.
conn.execute("UPDATE flashcards SET due_at=datetime('now', 'localtime', '-2 days') WHERE id=?", (card_id,))
conn.commit()
due = get_due_flashcards(1, limit=5)
assert any(c["id"] == card_id for c in due), [c["id"] for c in due]
print(f"[B2] get_due_flashcards : {len(due)} carte(s) due(s), test incluse")

start_cards = get_session_start_cards(1, n=5)
assert any(c["id"] == card_id for c in start_cards), "carte due absente du sas d'entrée"
print(f"[B2] get_session_start_cards : {len(start_cards)} carte(s), carte due prioritaire OK")

related = get_related_flashcards(1, doc_id=999999)
assert related == [] or isinstance(related, list)
print("[B2] get_related_flashcards OK")

from db.answers import get_recurring_struggles, save_answer  # noqa: E402
from db.questions import save_assistant_exchange, save_question  # noqa: E402

doc_row = conn.execute("SELECT id FROM documents WHERE path='/tmp/test.pdf'").fetchone()
if doc_row is None:
    conn.execute("INSERT INTO documents (path, filename) VALUES ('/tmp/test.pdf', 'test.pdf')")
    conn.commit()
    doc_row = conn.execute("SELECT id FROM documents WHERE path='/tmp/test.pdf'").fetchone()
doc_id = doc_row["id"]

qid = save_question(
    doc_id=doc_id, scope_type="page", scope_label="p1", page_start=1, page_end=1,
    question={"question_type": "open", "question": "Q difficulté ?", "answer": "rep"},
    llm_model="test",
)
for _ in range(2):
    save_answer(question_id=qid, user_id=1, answer_text="faux", verdict="incorrect")
struggles = get_recurring_struggles(1)
assert any(s["question_id"] == qid for s in struggles), struggles
print(f"[B2] get_recurring_struggles : {len(struggles)} difficulté(s), question test incluse")

# scope_type qa_follow_up
ex_id = save_assistant_exchange(
    doc_id=doc_id, page=1, user_question="pourquoi ?", llm_answer="parce que.",
    scope_type="qa_follow_up",
)
row = conn.execute("SELECT scope_type FROM questions WHERE id=?", (ex_id,)).fetchone()
assert row["scope_type"] == "qa_follow_up", dict(row)
print("[B4] save_assistant_exchange(scope_type='qa_follow_up') OK")

# page_dwell
from db.page_dwell import get_page_dwell, save_page_dwell  # noqa: E402

save_page_dwell(1, {1: 12.5, 3: 4.0}, {1: 2, 3: 1})
rows = get_page_dwell(1)
assert len(rows) == 2 and rows[0]["dwell_s"] == 12.5, rows
print("[B4] save_page_dwell/get_page_dwell OK")

# ── B4 : compute_alpha branché ────────────────────────────────────────────────
from metacog.profile import compute_alpha  # noqa: E402

assert compute_alpha(0) == 1.0 and abs(compute_alpha(5) - 0.5) < 1e-9 and compute_alpha(10_000) == 0.05
print("[B4] compute_alpha OK")

# ── A1 : localisation de citations (logique pure) ────────────────────────────
from reader.highlights import find_quote_rects, normalize_quote, rects_to_canvas  # noqa: E402

assert normalize_quote("  La  ﬁgure   montre…  ") == "La figure montre..."
fake_page = {"la figure montre un cercle parfait": [(10.0, 20.0, 110.0, 32.0)]}

def fake_search(needle: str):
    return fake_page.get(needle.lower().strip(), [])

rects = find_quote_rects(fake_search, "La figure montre un cercle parfait")
assert rects == [(10.0, 20.0, 110.0, 32.0)], rects
assert find_quote_rects(fake_search, "citation totalement hallucinée par le LLM") == []
assert find_quote_rects(fake_search, "court") == []
canvas_rects = rects_to_canvas(rects, scale=2.0, offset_x=26, offset_y=100)
assert canvas_rects == [(46.0, 140.0, 246.0, 164.0)], canvas_rects
print("[A1] find_quote_rects + rects_to_canvas OK")

# ── A2 : parsers highlights ───────────────────────────────────────────────────
from llm.schema_json import parse_evaluation, parse_follow_up, parse_highlights, parse_intervention  # noqa: E402

items = parse_highlights({"highlights": [
    {"quote": "une citation suffisamment longue pour passer", "purpose": "key"},
    {"quote": "court", "purpose": "explain"},
    "une citation brute en chaîne de caractères directe",
    {"quote": "purpose invalide mais citation assez longue", "purpose": "banana"},
    {"quote": "quatrième citation valide mais au-delà du plafond de trois"},
]})
assert len(items) == 3 and items[0]["purpose"] == "key" and items[2]["purpose"] == "explain", items
assert parse_highlights({}) == []
print("[A2] parse_highlights (filtre, alias, plafond) OK")

fu = parse_follow_up({"answer": "Voici la réponse.", "highlights": [{"quote": "une citation suffisamment longue ici aussi"}]})
assert fu and len(fu["highlights"]) == 1
ev = parse_evaluation({"verdict": "correct", "feedback": "Bien.", "completion": "", "hint": ""})
assert ev and ev["highlights"] == []
iv = parse_intervention({"should_intervene": True, "kind": "review_flashcard", "message": "On révise ?", "question": ""})
assert iv and iv["kind"] == "review_flashcard"
print("[A2] parse_follow_up/evaluation/intervention (review_flashcard) OK")

# ── Prompts : nouveaux blocs présents (fr + en) ───────────────────────────────
import i18n  # noqa: E402
from llm.prompts import (  # noqa: E402
    build_assistant_answer_prompt,
    build_evaluation_prompt,
    build_intervention_prompt,
    build_question_prompt,
    build_rephrasing_prompt,
)

struggles_arg = [{"question": "Définir une suite ?", "chapter_title": "Suites", "fail_count": 3}]
cards_arg = [{"front": "Définition d'une suite $u_n$ ?"}]
for lang in ("fr", "en"):
    i18n.set_lang(lang)
    p = build_question_prompt("Texte du paragraphe", past_struggles=struggles_arg)
    assert "Définir une suite ?" in p
    p = build_evaluation_prompt({"question": "Q"}, "rep", "para", past_struggles=struggles_arg)
    assert "Définir une suite ?" in p and "highlights" in p
    p = build_assistant_answer_prompt("texte page", "question ?", related_flashcards=cards_arg)
    assert "Définition d'une suite" in p and "highlights" in p
    p = build_rephrasing_prompt("para", 1)
    assert "highlights" in p
    p = build_intervention_prompt({"trigger": "flashcard_due", "page": 2, "due_flashcard_front": "Recto due"})
    assert "Recto due" in p and "review_flashcard" in p
print("[B3] prompts fr+en : difficultés passées, flashcards liées, flashcard due OK")

# ── i18n : toutes les nouvelles clés existent en fr et en ─────────────────────
new_keys = [
    "assistant.review_toast", "assistant.review_action", "assistant.review_done",
    "assistant.flashcard_review_title", "assistant.review_reveal",
    "assistant.review_correct", "assistant.review_partial", "assistant.review_incorrect",
    "assistant.focus_btn", "assistant.focus_stop",
    "focus.started", "focus.ended", "focus.stopped",
    "reader.chapter_done", "reader.chapter_recap_action",
    "reader.chapter_recap_loading", "reader.next_chapter_tease",
]
for lang in ("fr", "en"):
    for key in new_keys:
        assert key in i18n.STRINGS[lang], f"clé manquante [{lang}] {key}"
i18n.set_lang("fr")
print(f"[i18n] {len(new_keys)} nouvelles clés présentes en fr et en OK")

print("\nTOUS LES TESTS HORS-UI PASSENT ✓")
