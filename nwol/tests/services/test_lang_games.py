# Jeux et micro-items construits depuis le texte (plan § 10.3 ; V6).
import pytest

from services import lang_games as games
from services.lang_text import segment


def _episode(format_="dialogue"):
    lines = [
        ("Lucía", "Hola, Pablo. ¿Qué tal estás hoy?", "Salut, Pablo. Comment vas-tu ?"),
        ("Pablo", "Estoy bien, pero llego tarde otra vez.", "Je vais bien, mais j'arrive en retard."),
        ("Lucía", "¿Quieres un café con leche?", "Tu veux un café au lait ?"),
        ("Pablo", "Sí, por favor. Un café grande.", "Oui, s'il te plaît. Un grand café."),
        ("Carmen", "Buenos días. ¿Hay pan fresco?", "Bonjour. Il y a du pain frais ?"),
        ("Lucía", "Sí, el pan está en la mesa.", "Oui, le pain est sur la table."),
    ]
    glossary = [
        {"form": "Hola", "lemma": "hola", "translation": "salut"},
        {"form": "café", "lemma": "café", "translation": "café", "transparent": True},
        {"form": "leche", "lemma": "leche", "translation": "lait"},
        {"form": "pan", "lemma": "pan", "translation": "pain"},
        {"form": "mesa", "lemma": "mesa", "translation": "table"},
        {"form": "fresco", "lemma": "fresco", "translation": "frais"},
        {"form": "tarde", "lemma": "tarde", "translation": "tard"},
    ]
    out = []
    for speaker, text, tr in lines:
        tokens = segment(text)
        for tok in tokens:
            for gi, g in enumerate(glossary):
                if tok["w"] and tok["text"] == g["form"]:
                    tok["g"] = gi
        out.append({"speaker": speaker, "text": text, "translation": tr, "tokens": tokens})
    return {
        "id": 1, "format": format_, "lines": out, "glossary": glossary,
        "point": {"examples": ["Estoy bien", "está en la mesa"],
                  "variants": [{"example": "Estoy bien", "distractors": ["Soy bien", "Estás bien"]},
                               {"example": "está en la mesa", "distractors": ["es en la mesa"]}]},
    }


@pytest.mark.parametrize("kind", ["completer_replique", "qui_a_dit", "remettre_en_ordre", "apparier",
                                  "trouver_dans_le_texte", "bonne_forme"])
def test_each_latin_game_is_built_and_its_key_grades_true(kind):
    game = games.build_game(kind, _episode(), "latin", seed=7, prefix="jeux")
    assert game and game["items"]
    for item in game["items"]:
        assert games.grade(item, item["expected"]) is True
        assert item["ref"].startswith(f"jeux.{kind}.")


def test_unanswered_is_none_and_wrong_is_false():
    item = games.build_game("bonne_forme", _episode(), "latin", 1, "p")["items"][0]
    assert games.grade(item, None) is None and games.grade(item, "") is None
    assert games.grade(item, "Soy bien") is False
    # Les accents comptent (la bonne forme est souvent affaire d'accent).
    assert games._same("está", "esta") is False


def test_who_said_it_needs_a_dialogue():
    assert games.build_game("qui_a_dit", _episode("lettre"), "latin", 1, "p") is None


def test_last_game_is_the_easiest_and_recent_games_are_avoided():
    ep = _episode()
    chosen = games.choose_games(ep, "latin", seed=3, recent_kinds=[])
    assert len(chosen) == 2 and chosen[-1]["ease"] == 1
    assert chosen[0]["ease"] >= chosen[1]["ease"]
    avoid = [[g["kind"] for g in chosen]]
    again = games.choose_games(ep, "latin", seed=3, recent_kinds=avoid)
    assert not {g["kind"] for g in again} & set(avoid[0]) or len(games.GAMES) < 4


def test_variety_over_several_runs():
    ep = _episode()
    kinds = set()
    recent: list[list[str]] = []
    for seed in range(8):
        chosen = games.choose_games(ep, "latin", seed=seed, recent_kinds=recent)
        kinds |= {g["kind"] for g in chosen}
        recent.insert(0, [g["kind"] for g in chosen])
    assert len(kinds) >= 4


def test_seed_makes_games_reproducible():
    a = games.choose_games(_episode(), "latin", seed=11, recent_kinds=[])
    b = games.choose_games(_episode(), "latin", seed=11, recent_kinds=[])
    assert a == b


def test_point_micro_items_are_three():
    items = games.point_micro_items(_episode(), "latin", seed=5)
    assert len(items) == 3 and items[0]["kind"] == "trouver_dans_le_texte"


def test_ordering_game_keeps_logical_order_for_rtl():
    """L'ordre attendu est l'ordre logique du texte, y compris en arabe : c'est
    le front qui l'affiche de droite à gauche (A11)."""
    tokens = segment("ذَهَبَ الْوَلَدُ إِلَى الْمَدْرَسَةِ")
    ep = {"id": 2, "format": "recit", "glossary": [], "point": {},
          "lines": [{"speaker": "Narrateur", "text": "", "translation": "L'enfant est allé à l'école.",
                     "tokens": tokens}]}
    item = games.build_game("remettre_en_ordre", ep, "arabe", 1, "p")["items"][0]
    assert item["expected"][0] == "ذَهَبَ"
    assert games.grade(item, item["expected"]) is True
    assert games.grade(item, list(reversed(item["expected"]))) is False


def test_arabic_games_carry_script_units():
    tokens = segment("ذَهَبَ الْوَلَدُ إِلَى الْمَدْرَسَةِ")
    ep = {"id": 3, "format": "recit", "glossary": [], "point": {},
          "lines": [{"speaker": "Narrateur", "text": "", "translation": "", "tokens": tokens}]}
    for kind in ("lettre_forme", "lire_vocalise", "retrouver_la_lettre"):
        game = games.build_game(kind, ep, "arabe", 4, "p")
        assert game, kind
        assert all(item["units"] for item in game["items"])
        assert all(games.grade(item, item["expected"]) for item in game["items"])


def test_mandarin_games():
    pytest.importorskip("pypinyin")
    ep = {"id": 4, "format": "dialogue", "point": {}, "lines": [],
          "glossary": [{"form": f, "lemma": f, "translation": t} for f, t in
                       (("你好", "bonjour"), ("朋友", "ami"), ("老师", "professeur"), ("学生", "étudiant"))]}
    for kind in ("caractere_sens", "caractere_pinyin", "ton_du_caractere"):
        game = games.build_game(kind, ep, "hanzi", 2, "p")
        assert game and all(games.grade(it, it["expected"]) for it in game["items"]), kind
