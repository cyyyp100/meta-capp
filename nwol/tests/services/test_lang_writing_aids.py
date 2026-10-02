# Aides déterministes des écritures (plan A4-A5, G5-G6, G11-G13, M6, M8, N1-N5 ;
# tests V3-V4). Rien ici ne dépend de Clikoda : c'est tout l'intérêt.
import pytest

from services import lang_arabic as arabic
from services import lang_mandarin as mandarin
from services.lang_latin import de_gender_conflicts, faux_ami, is_transparent
from services.lang_text import find_token_span, jaccard, segment, word_diff


# ── Découpage commun ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "¡Hola, Pablo! ¿Qué tal?", "I don't know, it's well-known.", "Das ist das Haus.",
    "كَيْفَ حَالُكَ؟ أَنَا بِخَيْرٍ.",
])
def test_segment_rebuilds_the_line_exactly(text):
    tokens = segment(text)
    assert "".join(t["text"] for t in tokens) == text
    assert all(t["text"].strip() for t in tokens if t["w"])


def test_segment_keeps_apostrophes_and_arabic_vowels_inside_words():
    assert [t["text"] for t in segment("don't stop") if t["w"]] == ["don't", "stop"]
    assert [t["text"] for t in segment("كِتَابٌ جَمِيلٌ") if t["w"]] == ["كِتَابٌ", "جَمِيلٌ"]


def test_find_token_span_and_word_diff():
    tokens = segment("Estoy muy bien, gracias.")
    assert [tokens[i]["text"] for i in find_token_span(tokens, "muy bien")] == ["muy", "bien"]
    ops = word_diff("Estoy muy bien.", "estoy bien")
    assert {"op": "missing", "text": "muy"} in ops and ops[0] == {"op": "equal", "text": "estoy"}
    # Les accents comptent : « esta » n'est pas « está ».
    assert any(o["op"] != "equal" for o in word_diff("está", "esta"))


def test_jaccard_ignores_names_and_french_stopwords():
    a = "Lucía et Pablo préparent une fête dans le café"
    b = "Lucía et Pablo réparent la voiture dans le garage"
    assert jaccard(a, b, ignore={"Lucía", "Pablo"}) < 0.3


# ── Arabe ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("word,expected", [
    ("كِتَابٌ", "kitābun"), ("كِتَابْ", "kitāb"), ("الشَّمْسُ", "aš-šamsu"), ("الْقَمَرُ", "al-qamaru"),
    ("مَدْرَسَةٌ", "madrasatun"), ("مَدْرَسَة", "madrasa"), ("مُحَمَّدٌ", "muḥammadun"), ("بَيْتٌ", "baytun"),
    ("يَوْمٌ", "yawmun"), ("أَنَا", "anā"), ("شُكْرًا", "šukran"), ("وَالْبَيْتُ", "wa-l-baytu"),
    ("لِلْبَيْتِ", "li-l-bayti"), ("هٰذَا", "hāḏā"), ("عَلَى", "ʿalā"), ("سَأَلَ", "saʾala"), ("نُورٌ", "nūrun"),
    ("اِسْمِي", "ismī"),
    # Lettres muettes : alif du pluriel verbal (après ū ou la diphtongue aw),
    # alif après une kasra, wāw après le tanwīn.
    ("كَتَبُوا", "katabū"), ("يَكْتُبُوا", "yaktubū"), ("دَعَوْا", "daʿaw"), ("بَابًا", "bāban"),
    ("مِائَةٌ", "miʾatun"), ("عَمْرٌو", "ʿamrun"), ("أُولٰئِكَ", "ulāʾika"), ("الْأُولَى", "al-ūlā"),
])
def test_transliteration_follows_the_din_scheme(word, expected):
    assert arabic.transliterate_word(word) == expected


def test_transliteration_of_a_sentence_keeps_punctuation():
    assert arabic.transliterate("كَيْفَ حَالُكَ؟") == "kayfa ḥāluka?"


def test_strip_and_partial_vocalization():
    text = "ذَهَبَ الْوَلَدُ إِلَى الْمَدْرَسَةِ"
    assert arabic.strip_harakat(text) == "ذهب الولد إلى المدرسة"
    # On garde les voyelles du 2e mot seulement.
    partial = arabic.partial_vocalization(text, keep=lambda i, bare: i == 1)
    assert partial.split(" ")[1] == "الْوَلَدُ" and partial.split(" ")[0] == "ذهب"


def test_vocalization_ratio_detects_missing_vowels():
    assert arabic.vocalization_ratio("ذَهَبَ الْوَلَدُ إِلَى الْمَدْرَسَةِ") >= 0.8
    assert arabic.vocalization_ratio("ذهب الولد إلى المدرسة") == 0.0
    assert arabic.vocalization_ratio("hello") == 0.0


def test_stem_vocalized_ignores_the_case_ending():
    assert arabic.stem_vocalized("كِتَابٌ") == arabic.stem_vocalized("كِتَابِ")
    assert arabic.stem_vocalized("كِتَابٌ") != arabic.stem_vocalized("كُتُبٌ")


def test_contextual_letter_forms():
    assert arabic.contextual_form("بيت", 0) == "initial"
    assert arabic.contextual_form("بيت", 1) == "medial"
    assert arabic.contextual_form("بيت", 2) == "final"
    # dāl ne se lie pas à gauche : la lettre suivante repart en forme initiale.
    assert arabic.contextual_form("ولد", 1) == "initial"


# ── Mandarin ──────────────────────────────────────────────────────────────────

def test_tokens_must_rebuild_the_sentence():
    assert mandarin.tokens_rebuild("你好，我是小王。", ["你好", "，", "我", "是", "小王", "。"])
    assert not mandarin.tokens_rebuild("你好，我是小王。", ["你好", "我", "是", "小王"])


def test_traditional_characters_are_detected():
    assert mandarin.traditional_in("我們是朋友") == ["們"]
    assert mandarin.traditional_in("我们是朋友") == []


pinyin = pytest.importorskip("pypinyin")


def test_pinyin_is_computed_per_token_with_tones():
    py = mandarin.token_pinyin("你好")
    assert [s["mark"] for s in py["syllables"]] == ["nǐ", "hǎo"]
    assert [s["num"] for s in py["syllables"]] == ["ni3", "hao3"]
    assert mandarin.token_pinyin("银行")["syllables"][1]["mark"] == "háng"  # résolu par le mot
    assert mandarin.token_pinyin("的")["syllables"][0]["tone"] == 5
    assert mandarin.token_pinyin("得")["syllables"][0]["mark"] == "de"  # lecture isolée


def test_unresolved_heteronym_is_flagged_suspect():
    assert not mandarin.token_pinyin("银行")["suspect"]
    assert not mandarin.token_pinyin("是")["suspect"]  # lecture rare au dictionnaire : pas un vrai doute
    assert mandarin.token_pinyin("好好地")["suspect"] in (False, True)  # jamais d'exception


def test_sandhi_rules():
    tokens = ["你好", "，", "我", "不", "是", "一", "个", "老师", "。"]
    notes = mandarin.sandhi_notes(tokens, [mandarin.token_pinyin(t) for t in tokens])
    rules = {(n["rule"], n["hanzi"], n["to"]) for n in notes}
    assert ("tone3", "你", "ní") in rules
    assert ("bu", "不", "bú") in rules
    assert ("yi", "一", "yí") in rules
    first = ["第", "一"]
    assert mandarin.sandhi_notes(first, [mandarin.token_pinyin(t) for t in first]) == []


def test_components_come_from_the_registry():
    assert [c["char"] for c in mandarin.components_in("河")] == ["氵"]


# ── Langues latines ───────────────────────────────────────────────────────────

def test_transparent_words():
    assert is_transparent("familia", "la famille")
    assert is_transparent("restaurante", "restaurant")
    assert not is_transparent("perro", "chien")
    assert not is_transparent("de", "de")


def test_false_friends_from_the_static_list():
    assert "enceinte" in faux_ami("espagnol", "embarazada")["note"]
    assert faux_ami("espagnol", "casa") is None


def test_german_gender_is_checked_only_on_unambiguous_articles():
    glossary = [{"form": "Haus", "lemma": "Haus", "pos": "nom", "gender": "n"},
                {"form": "Mann", "lemma": "Mann", "pos": "nom", "gender": "m"}]
    assert de_gender_conflicts(["das", "Haus", "einen", "Mann"], glossary) == []
    assert de_gender_conflicts(["eine", "Haus"], glossary) == ["eine Haus (n)"]
    # « der » est ambigu (masculin nominatif, féminin datif) : jamais bloquant.
    assert de_gender_conflicts(["der", "Haus"], glossary) == []
