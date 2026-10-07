# config/subjects.py — Le vocabulaire des matières.
#
# SOURCE DE VÉRITÉ UNIQUE, comme `config/question_types.py` pour les types de
# questions. Une matière est une CLÉ stable (« physique », « anglais ») : c'est
# elle que le LLM choisit à l'import d'un document (llm/prompts.py), que le
# parseur ramène à sa forme canonique (llm/schema_json.py), que la base garde
# (`documents.subject`, `subject_profile`), que le quiz filtre et que
# l'interface traduit (frontend/src/features/stats/labels.ts, vérifié par
# tests/test_subjects.py).
#
# La liste est FERMÉE. Un modèle libre de nommer la matière écrirait « IA », puis
# « apprentissage automatique », puis « machine learning » : trois matières,
# trois niveaux, pour un seul domaine. Ce qu'aucune clé ne décrit tombe dans
# « culture ».
#
# Deux familles :
#   - les DISCIPLINES ;
#   - une matière PAR LANGUE : celles du catalogue du module Langues, sous le même
#     code (le nom français en minuscules), pour qu'une langue lue, jouée en quiz
#     ou pratiquée en séance soit une seule et même matière. L'ancienne matière
#     fourre-tout « langues » a été répartie par la migration v39.
#
# Ce module dit ce qu'est une matière ; QUELLES matières un apprenant possède,
# c'est services/subjects.py.
from __future__ import annotations

import re

from config.settings import LANGUAGE_SCRIPTS
from utils.text import fold

DISCIPLINES: tuple[str, ...] = (
    "mathématiques", "physique", "chimie", "biologie", "sciences",
    "informatique", "technologie", "histoire", "géographie", "français",
    "philosophie", "littérature", "économie", "sciences-sociales", "droit",
    "gestion", "psychologie", "sociologie", "arts", "musique",
    "médecine", "sport", "religion", "culture",
)
# Le repli : ce qu'aucune autre matière ne décrit.
FALLBACK_SUBJECT = "culture"

# Une matière par langue du catalogue (services/lang.py:LANGUAGES, mêmes codes).
LANGUAGE_SUBJECTS: tuple[str, ...] = tuple(LANGUAGE_SCRIPTS)

SUBJECTS: tuple[str, ...] = DISCIPLINES + LANGUAGE_SUBJECTS

# L'ancienne matière unique des langues : plus jamais attribuée (migration v39).
LEGACY_LANGUAGES_SUBJECT = "langues"

# Comment un modèle, un titre ou une fiche nomme une langue (forme repliée,
# cf. `subject_token`) : alias du parseur ET repères de `detect_language`.
LANGUAGE_NAMES: dict[str, tuple[str, ...]] = {
    "anglais": ("anglais", "anglaise", "english"),
    "espagnol": ("espagnol", "espagnole", "spanish", "espanol", "castillan"),
    "allemand": ("allemand", "allemande", "german", "deutsch"),
    "italien": ("italien", "italienne", "italian", "italiano"),
    "portugais": ("portugais", "portugaise", "portuguese", "portugues"),
    "néerlandais": ("neerlandais", "neerlandaise", "dutch", "nederlands"),
    "polonais": ("polonais", "polish", "polski"),
    "suédois": ("suedois", "suedoise", "swedish", "svenska"),
    "turc": ("turc", "turkish", "turkce"),
    "roumain": ("roumain", "roumaine", "romanian"),
    "indonésien": ("indonesien", "indonesienne", "indonesian"),
    "vietnamien": ("vietnamien", "vietnamienne", "vietnamese"),
    "russe": ("russe", "russian"),
    "grec": ("grec", "grecque", "greek"),
    "coréen": ("coreen", "coreenne", "korean"),
    "mandarin": ("mandarin", "chinois", "chinoise", "chinese"),
    "japonais": ("japonais", "japonaise", "japanese"),
    "arabe": ("arabe", "arabic"),
    "hébreu": ("hebreu", "hebraique", "hebrew"),
    "hindi": ("hindi",),
    "thaï": ("thai", "thaie"),
}

# « Les langues » sans dire laquelle : ce n'est plus une matière. Le parseur
# cherche alors la langue dans ce que le modèle a écrit d'autre (résumé,
# mots-clés), cf. llm/schema_json.parse_document_digest.
GENERIC_LANGUAGE_TOKENS: frozenset[str] = frozenset({
    "langue", "langues", "language", "languages",
    "langue_etrangere", "langues_etrangeres", "foreign_language", "foreign_languages",
})

# Autres façons d'écrire une discipline (forme repliée).
_ALIASES: dict[str, str] = {
    "math": "mathématiques",
    "maths": "mathématiques",
    "mathematics": "mathématiques",
    "algebre": "mathématiques",
    "analyse": "mathématiques",
    "geometrie": "mathématiques",
    "statistiques": "mathématiques",
    "physics": "physique",
    "mecanique": "physique",
    "chemistry": "chimie",
    "biology": "biologie",
    "svt": "biologie",
    "science": "sciences",
    "informatics": "informatique",
    "computing": "informatique",
    "computer_science": "informatique",
    "programmation": "informatique",
    "technology": "technologie",
    "ingenierie": "technologie",
    "engineering": "technologie",
    "history": "histoire",
    "geography": "géographie",
    "french": "français",
    "philosophy": "philosophie",
    "literature": "littérature",
    "economics": "économie",
    "eco": "économie",
    "ses": "économie",
    "social_sciences": "sciences-sociales",
    "sciences_humaines": "sciences-sociales",
    "law": "droit",
    "management": "gestion",
    "comptabilite": "gestion",
    "psychology": "psychologie",
    "sociology": "sociologie",
    "art": "arts",
    "art_plastique": "arts",
    "arts_plastiques": "arts",
    "music": "musique",
    "medicine": "médecine",
    "sante": "médecine",
    "health": "médecine",
    "sports": "sport",
    "eps": "sport",
    "theologie": "religion",
    "theology": "religion",
    "general": "culture",
    "generale": "culture",
    "culture_generale": "culture",
}


def subject_token(value) -> str:
    """Forme repliée d'un nom de matière : minuscules, sans accent, « _ » entre
    les mots (« Sciences sociales » → « sciences_sociales »)."""
    return re.sub(r"[^a-z0-9]+", "_", fold(str(value or ""))).strip("_")


_CANONICAL: dict[str, str] = {
    **_ALIASES,
    **{name: code for code, names in LANGUAGE_NAMES.items() for name in names},
    **{subject_token(key): key for key in SUBJECTS},
}

_LANGUAGE_SET = frozenset(LANGUAGE_SUBJECTS)


def canonical_subject(value) -> str | None:
    """La clé d'une matière, quelle que soit la façon dont on l'a écrite
    (« Maths », « English », « Informatique », « computer science »), ou None si
    elle n'est pas au vocabulaire."""
    return _CANONICAL.get(subject_token(value))


def is_language(subject: str | None) -> bool:
    """Vrai pour une matière de langue (clé canonique)."""
    return subject in _LANGUAGE_SET


def is_generic_language(value) -> bool:
    """« Langues », « language »… : une langue sans dire laquelle."""
    return subject_token(value) in GENERIC_LANGUAGE_TOKENS


_NAME_TO_LANGUAGE: dict[str, str] = {
    name: code for code, names in LANGUAGE_NAMES.items() for name in names
}
_LANGUAGE_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_NAME_TO_LANGUAGE, key=len, reverse=True)) + r")\b"
)


def detect_language(text: str) -> str | None:
    """La langue que nomme le plus un texte (« grammaire anglaise », « English
    vocabulary »), ou None s'il n'en nomme aucune. À égalité, la première citée.

    Repère déterministe, sans LLM : il sert quand le modèle n'a pas dit quelle
    langue (repli hors ligne, « langues » générique) et à la migration v39."""
    counts: dict[str, int] = {}
    # « english_grammar.pdf » : le tiret bas est une lettre pour \b, pas ici.
    for match in _LANGUAGE_PATTERN.finditer(fold(text or "").replace("_", " ")):
        code = _NAME_TO_LANGUAGE[match.group(1)]
        counts[code] = counts.get(code, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda code: counts[code])
