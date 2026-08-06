# Tests des parseurs des types interactifs (plan2) : correction côté client, donc
# validation STRICTE — un exercice dont la solution est incohérente doit être rejeté
# (un exercice mal corrigé est pire que pas d'exercice). + production 2 paliers (plan1).
from llm.schema_json import (
    parse_session_cloze,
    parse_session_matching,
    parse_session_ordering,
    parse_session_phonetics,
    parse_session_production,
    parse_session_reading,
    parse_session_transform,
)


# ── cloze ─────────────────────────────────────────────────────────────────────

def test_cloze_bank_accepts_coherent_item():
    out = parse_session_cloze({
        "mode": "bank",
        "sentences": [
            {"text": "Je ___ au marché le ___ .", "blanks": ["vais", "samedi"],
             "options": ["vais", "vas", "samedi", "dimanche"], "translation": "..."},
        ],
    })
    assert out["kind"] == "cloze" and out["mode"] == "bank"
    assert len(out["sentences"]) == 1
    assert out["sentences"][0]["options"]


def test_cloze_bank_rejects_blank_absent_from_options():
    # « samedi » n'est pas dans la banque → item non corrigeable → rejeté.
    out = parse_session_cloze({
        "mode": "bank",
        "sentences": [
            {"text": "Je ___ le ___ .", "blanks": ["vais", "samedi"],
             "options": ["vais", "vas", "dimanche"]},
        ],
    })
    assert out is None


def test_cloze_rejects_blank_count_mismatch():
    # 2 trous mais 1 seule réponse → incohérent.
    out = parse_session_cloze({
        "mode": "free",
        "sentences": [{"text": "Je ___ au ___ .", "blanks": ["vais"]}],
    })
    assert out is None


def test_cloze_free_has_no_options():
    out = parse_session_cloze({
        "mode": "free",
        "sentences": [{"text": "Je ___ .", "blanks": ["vais"], "translation": "I go."}],
    })
    assert out["mode"] == "free"
    assert "options" not in out["sentences"][0]


# ── ordering ──────────────────────────────────────────────────────────────────

def test_ordering_accepts_permutation():
    out = parse_session_ordering({
        "task": "ordre",
        "items": [{"tokens": ["mange", "Je", "une", "pomme"],
                   "solution": ["Je", "mange", "une", "pomme"], "translation": "..."}],
    })
    assert out["kind"] == "ordering" and len(out["items"]) == 1


def test_ordering_rejects_token_solution_mismatch():
    # tokens contient un mot absent de solution → multiset différent → rejeté.
    out = parse_session_ordering({
        "items": [{"tokens": ["Je", "mange", "ENORME"], "solution": ["Je", "mange", "vite"]}],
    })
    assert out is None


# ── matching ──────────────────────────────────────────────────────────────────

def test_matching_dedupes_and_requires_two_pairs():
    out = parse_session_matching({
        "task": "relie",
        "pairs": [
            {"left": "la maison", "right": "the house"},
            {"left": "la maison", "right": "duplicate"},  # gauche en double → ignorée
            {"left": "le chien", "right": "the dog"},
        ],
    })
    assert len(out["pairs"]) == 2


def test_matching_rejects_single_pair():
    assert parse_session_matching({"pairs": [{"left": "x", "right": "y"}]}) is None


# ── transform ─────────────────────────────────────────────────────────────────

def test_transform_parses_items():
    out = parse_session_transform({
        "task": "passé composé",
        "items": [{"source": "Je mange.", "expected": "J'ai mangé.", "focus": "passé", "hint": "avoir"}],
    })
    assert out["kind"] == "transform" and out["items"][0]["expected"] == "J'ai mangé."


# ── phonétique enrichie (plan2) ───────────────────────────────────────────────

def test_phonetics_parses_structured_drills():
    out = parse_session_phonetics({
        "focus_sound": "[ɲ]",
        "minimal_pairs": [{"a": "agneau", "b": "anneau", "note": "gn"}],
        "drills": [
            {"kind": "read", "target": "le mignon agneau", "phonetic": "...", "translation": "..."},
            {"kind": "stress", "word": "telefono", "syllables": ["te", "le", "fo", "no"], "stressed_index": 1, "translation": "..."},
            {"kind": "spell_to_sound", "written": "gnocchi", "options": ["ˈɲɔkki", "ɡnotʃi"], "answer": 0, "translation": "..."},
            {"kind": "stress", "word": "x", "syllables": ["x"], "stressed_index": 5},  # hors borne → rejeté
        ],
    })
    kinds = [d["kind"] for d in out["drills"]]
    assert kinds == ["read", "stress", "spell_to_sound"]


# ── production 2 paliers (plan1, Axe 2) ───────────────────────────────────────

def test_production_two_step_shape():
    out = parse_session_production({
        "instructions": "...",
        "guided": {"prompt": "Complète : Je voudrais ___ une table.", "expected": "réserver", "hint": "verbe"},
        "free": {"prompt": "Demande une table à ta façon.", "reference": "Une table pour deux ?", "hint": ""},
    })
    assert out["mode"] == "two_step"
    assert out["guided"]["expected"] == "réserver"
    assert out["free"]["reference"]


def test_production_legacy_tasks_still_supported():
    out = parse_session_production({
        "instructions": "...",
        "tasks": [{"prompt": "produis", "context": "", "reference": "modèle", "hint": ""}],
    })
    assert out["mode"] == "tasks" and len(out["tasks"]) == 1


# ── question d'inférence (plan1, Axe 3) ───────────────────────────────────────

def test_reading_preserves_inference_depth():
    out = parse_session_reading({
        "text_target": "Il pleut, Marco prend son parapluie.",
        "questions": [
            {"question": "Que prend Marco ?", "choices": ["A: parapluie", "B: rien"], "correct": "A"},
            {"question": "Quel temps fait-il dehors ?", "choices": ["A: soleil", "B: pluie"], "correct": "B", "depth": "inference"},
        ],
    })
    depths = [q["depth"] for q in out["questions"]]
    assert depths == ["literal", "inference"]
