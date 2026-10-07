"""Valide les données statiques du module langues (plan S2, V11).

Rejoue les invariants de services/lang_static.py sur chaque fichier de
nwol/data/lang/ : programmes (ids, ordre continu, CECR croissant, prérequis
antérieurs, groupes de bilan par blocs de 6), tests de niveau (clés, points du
programme), phrases de survie et clavier, faux-amis, leçons écrites à la main
(lessons/<langue>.json, s'il existe) et registres d'écriture. À lancer après
toute relecture :

    python tools/validate_lang_data.py

Code de sortie 1 si une erreur est trouvée. La même vérification tourne dans la
suite de tests (tests/services/test_lang_static.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nwol"))


def check_all() -> dict[str, list[str]]:
    from config.settings import LANG_PILOT_LANGUAGES
    from services.lang_static import (
        load_json,
        script_registry,
        validate_faux_amis,
        validate_lessons_file,
        validate_onboarding,
        validate_placement,
        validate_program,
    )

    report: dict[str, list[str]] = {}
    for language in LANG_PILOT_LANGUAGES:
        program = load_json("program", f"{language}.json")
        if program is None:
            report[f"program/{language}.json"] = ["absent"]
            continue
        report[f"program/{language}.json"] = validate_program(program, language)
        ids = {p["id"] for p in program.get("points") or []}
        placement = load_json("placement", f"{language}.json")
        report[f"placement/{language}.json"] = (
            validate_placement(placement, language, ids) if placement else ["absent"]
        )
        onboarding = load_json("onboarding", f"{language}.json")
        report[f"onboarding/{language}.json"] = (
            validate_onboarding(onboarding, language) if onboarding else ["absent"]
        )
        if language in ("espagnol", "anglais", "allemand"):
            fa = load_json("helpers", f"faux_amis_{language}.json")
            report[f"helpers/faux_amis_{language}.json"] = validate_faux_amis(fa, language) if fa else ["absent"]
        lessons = load_json("lessons", f"{language}.json")
        if lessons is not None:  # facultatif : Clikoda écrit les leçons qui manquent
            report[f"lessons/{language}.json"] = validate_lessons_file(lessons, language, ids)
    arabic = script_registry("arabic")
    letters = arabic.get("letters") or []
    errors = []
    if len(letters) != 28:
        errors.append(f"{len(letters)} lettres au lieu de 28")
    for letter in letters:
        if set(letter.get("forms") or {}) != {"isolated", "initial", "medial", "final"}:
            errors.append(f"{letter.get('id')} : quatre formes requises")
    report["scripts/arabic.json"] = errors
    translit = script_registry("arabic_translit")
    missing = [ch for ch in (letter["char"] for letter in letters) if ch not in (translit.get("consonants") or {})
               and ch not in ("ا",)]
    report["scripts/arabic_translit.json"] = [f"lettres sans translittération : {''.join(missing)}"] if missing else []
    sounds = script_registry("mandarin_sounds")
    report["scripts/mandarin_sounds.json"] = [] if len(sounds.get("tones") or []) == 5 else ["cinq tons attendus"]
    comps = script_registry("mandarin_components").get("components") or []
    report["scripts/mandarin_components.json"] = [] if len(comps) >= 50 else [f"{len(comps)} clés, 50 attendues"]
    return report


def main() -> int:
    report = check_all()
    failed = False
    for name, errors in report.items():
        status = "ok" if not errors else f"{len(errors)} erreur(s)"
        print(f"{name:<40} {status}")
        for err in errors[:20]:
            print(f"    - {err}")
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
