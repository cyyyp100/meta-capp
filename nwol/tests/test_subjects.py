"""`config/subjects.py` est la SEULE déclaration des matières.

La liste vivait en cinq copies (libellés backend, ensemble du parseur, chaîne du
prompt, libellés et clés i18n du frontend), tenues « en miroir » à la main : une
matière oubliée dans l'une retombait en silence sur « culture » ou s'affichait
sous sa clé brute. Ces tests échouent dès qu'un consommateur se remet à tenir sa
propre liste — et vérifient qu'il y a bien une matière par langue.
"""
from __future__ import annotations

import re
from pathlib import Path

from config import subjects as vocab

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def test_one_subject_per_language_of_the_catalogue():
    """Une langue lue, jouée en quiz ou pratiquée en séance est UNE matière :
    celle du module Langues, sous le même code."""
    from services.lang import LANGUAGES

    assert set(vocab.LANGUAGE_SUBJECTS) == {lang["code"] for lang in LANGUAGES}
    assert set(vocab.LANGUAGE_NAMES) == set(vocab.LANGUAGE_SUBJECTS)
    assert not set(vocab.DISCIPLINES) & set(vocab.LANGUAGE_SUBJECTS)
    assert vocab.LEGACY_LANGUAGES_SUBJECT not in vocab.SUBJECTS
    assert vocab.FALLBACK_SUBJECT in vocab.DISCIPLINES
    assert len(set(vocab.SUBJECTS)) == len(vocab.SUBJECTS)


def test_every_spelling_lands_on_its_key():
    for key in vocab.SUBJECTS:
        assert vocab.canonical_subject(key) == key
        assert vocab.canonical_subject(key.upper()) == key
    assert vocab.canonical_subject("Maths") == "mathématiques"
    assert vocab.canonical_subject("Computer science") == "informatique"
    assert vocab.canonical_subject("English") == "anglais"
    assert vocab.canonical_subject("Chinese") == "mandarin"
    assert vocab.canonical_subject("thai") == "thaï"
    # « Les langues » sans dire laquelle n'est plus une matière.
    assert vocab.canonical_subject("langues") is None
    assert vocab.is_generic_language("Languages")


def test_detect_language_names_the_most_cited_language():
    assert vocab.detect_language("English_grammar.pdf — verbes irréguliers anglais") == "anglais"
    assert vocab.detect_language("Cours d'espagnol, un mot d'anglais, puis l'espagnol") == "espagnol"
    assert vocab.detect_language("Vocabulario español") == "espagnol"
    assert vocab.detect_language("Les intégrales de Riemann") is None


def test_the_parser_and_the_prompt_read_the_vocabulary():
    import i18n
    from llm.prompts import build_document_digest_prompt
    from llm.schema_json import parse_document_digest

    for key in vocab.SUBJECTS:
        assert parse_document_digest({"subject": key})["subject"] == key
    for lang in ("fr", "en"):
        i18n.set_lang(lang)
        try:
            prompt = build_document_digest_prompt("Doc", "Texte")
        finally:
            i18n.set_lang("fr")
        for key in vocab.SUBJECTS:
            assert key in prompt, (lang, key)
        assert re.search(r"\blangues\b,", prompt) is None


def test_a_generic_language_answer_is_rescued_from_the_card():
    """Le modèle qui répond encore « langues » a souvent nommé la langue dans son
    résumé ou ses mots-clés : c'est elle que le document reçoit."""
    from llm.schema_json import parse_document_digest

    card = parse_document_digest(
        '{"subject": "langues", "summary": "Le subjonctif en espagnol.", "keywords": ["subjonctif"]}'
    )
    assert card["subject"] == "espagnol"
    assert parse_document_digest('{"subject": "langues", "summary": "x"}')["subject"] == "culture"


def test_the_offline_heuristic_names_the_language():
    from llm.ollama_client import _heuristic_subject

    assert _heuristic_subject("Grammaire anglaise : les verbes irréguliers") == "anglais"
    assert _heuristic_subject("Dictée et conjugaison du passé simple") == "français"


def test_the_frontend_names_every_subject():
    """Une matière sans libellé s'afficherait sous sa clé brute, dans les deux langues."""
    labels = (FRONTEND / "features" / "stats" / "labels.ts").read_text(encoding="utf-8")
    block = re.search(r"SUBJECT_I18N_KEYS: Record<string, string> = \{(.*?)\n\};", labels, re.S)
    assert block, "SUBJECT_I18N_KEYS introuvable dans labels.ts"
    keys = dict(re.findall(r'\n  "([^"]+)": "([^"]+)",', block.group(1)))
    assert set(vocab.SUBJECTS) <= set(keys)
    assert set(keys) - set(vocab.SUBJECTS) == {vocab.LEGACY_LANGUAGES_SUBJECT}

    i18n_source = (FRONTEND / "i18n" / "index.ts").read_text(encoding="utf-8")
    for subject, i18n_key in keys.items():
        assert i18n_source.count(f'"{i18n_key}":') == 2, (subject, i18n_key)  # FR + EN
