# tests/subject_helpers.py — Donner une matière à l'apprenant comme l'app le fait.
#
# Les matières d'un apprenant ne se déclarent pas : elles naissent d'un document
# importé (discipline) ou d'une séance faite dans une langue
# (services/subjects.py). Ces aides rejouent ces deux chemins.
from __future__ import annotations


def import_document(subject: str, name: str | None = None) -> int:
    """Un document de la bibliothèque, classé dans `subject`, sans question."""
    from db.documents import upsert_document

    stem = name or f"own-{subject}"
    return upsert_document(
        path=f"/tmp/{stem}.pdf",
        filename=f"{stem}.pdf",
        page_count=3,
        engine="test",
        has_toc=False,
        subject=subject,
    )


def complete_language_session(language: str, user_id: int = 1, status: str = "completed") -> int:
    """Une séance du feuilleton dans `language` (terminée par défaut)."""
    from db.lang_db import get_or_create_lang_profile
    from db.lang_episode_db import create_run, update_run

    profile = get_or_create_lang_profile(user_id, language)
    run_id = create_run(
        profile["id"], mode="episode", plan={}, episode_id=None,
        second_wave_episode_id=None, absence_days=None, study_date="2026-10-06",
    )
    update_run(run_id, status=status)
    return run_id


def own(*subjects: str) -> None:
    """Rend chaque matière à l'apprenant : un document pour une discipline, une
    séance terminée pour une langue."""
    from config.subjects import is_language

    for subject in subjects:
        if is_language(subject):
            complete_language_session(subject)
        else:
            import_document(subject)
