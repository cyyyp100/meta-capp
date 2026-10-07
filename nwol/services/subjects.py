# services/subjects.py — Les matières de l'apprenant.
#
# UNE liste, calculée ici et nulle part ailleurs : celle que le profil affiche
# (« Par matière », services/stats.py) et celle que le quiz propose
# (services/quiz.py). Deux apprenants n'ont donc pas les mêmes matières : elles
# naissent de ce que chacun importe, lit et pratique.
#
# Ce qu'EST une matière — le vocabulaire fermé, une matière par langue — est dans
# config/subjects.py.
from __future__ import annotations

from config.subjects import DISCIPLINES, canonical_subject, is_language
from db.documents import list_document_subjects
from db.lang_db import completed_sessions_by_language, get_all_lang_profiles
from db.sessions import finished_sessions_by_subject
from db.subjects import get_all_subjects
from db.user import DEFAULT_USER_ID
from utils.text import fold

__all__ = ["owned_subjects", "describe", "language_practice"]


def owned_subjects(user_id: int = DEFAULT_USER_ID) -> list[str]:
    """Les matières de l'apprenant : les disciplines, puis les langues, chacune
    par ordre alphabétique de sa clé.

    - une DISCIPLINE est à lui dès qu'un document de sa bibliothèque la porte (le
      LLM la choisit à l'import, `services.orchestrator`) ou qu'il y a déjà été
      mesuré en quiz ;
    - une LANGUE, dès qu'il a fait au moins une séance dans cette langue : une
      séance du module Langues menée au bout, la lecture d'un document de cette
      langue, ou un quiz où il y a répondu. Ouvrir une langue sans la pratiquer,
      ou seulement importer un document, ne suffit pas.

    Une matière dont le dernier document a été supprimé, et où rien n'a jamais été
    mesuré, n'est plus à lui ; ses mesures, s'il y en a, la gardent.
    """
    measured = {
        canonical_subject(row.get("subject"))
        for row in get_all_subjects(user_id)
        if int(row.get("questions_count") or 0) > 0
    }
    in_library = {canonical_subject(subject) for subject in list_document_subjects()}

    disciplines = (in_library | measured) & set(DISCIPLINES)
    languages = set(_language_sessions(user_id)) | {s for s in measured if is_language(s)}
    return sorted(disciplines, key=fold) + sorted(languages, key=fold)


def describe(subject: str) -> dict:
    """Ce que l'interface a besoin de savoir d'une matière en plus de sa clé :
    sa famille, et le drapeau d'une langue (celui de la page Langues)."""
    if not is_language(subject):
        return {"subject": subject, "kind": "discipline", "flag": ""}
    from services.lang import LANGUAGES

    flag = next((lang["flag"] for lang in LANGUAGES if lang["code"] == subject), "")
    return {"subject": subject, "kind": "language", "flag": flag}


def language_practice(user_id: int = DEFAULT_USER_ID) -> dict[str, dict]:
    """Par langue pratiquée : séances terminées dans cette langue (module Langues
    et lectures) et niveau CECR — celui du module, None si la langue n'y a jamais
    été jouée (le niveau d'un profil seulement ouvert ne mesure rien)."""
    in_module = completed_sessions_by_language(user_id)
    levels = {
        profile.get("language"): profile.get("level") or "A1"
        for profile in get_all_lang_profiles(user_id)
        if in_module.get(profile.get("language"))
    }
    return {
        code: {"sessions": count, "cefr": levels.get(code)}
        for code, count in _language_sessions(user_id).items()
    }


def _language_sessions(user_id: int) -> dict[str, int]:
    """Séances terminées dans chaque langue : celles du module Langues, plus les
    lectures de documents de cette langue."""
    counts: dict[str, int] = {}
    for sessions in (completed_sessions_by_language(user_id), finished_sessions_by_subject(user_id)):
        for raw, count in sessions.items():
            subject = canonical_subject(raw)
            if is_language(subject) and count:
                counts[subject] = counts.get(subject, 0) + count
    return counts
