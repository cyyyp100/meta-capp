"""Relecture des vocalisations arabes observées (plan A7, § 14 n° 7 du rapport 18).

Chaque mot arabe écrit par Clikoda laisse une trace dans `lang_vocalized_forms` :
son radical vocalisé (tout sauf les marques de la dernière lettre, qui portent
les désinences), rangé sous sa forme nue. Tant qu'aucune forme d'un mot n'est
`valide`, la vérification ne compare rien : chaque radical est enregistré comme
`candidat`. Dès qu'un relecteur en valide une, tout radical DIFFÉRENT du même
mot devient « suspect » à la génération suivante, et la bulle du tap montre la
forme validée.

Ce script est l'outil qui manquait pour passer une forme `valide` :

    python tools/review_vocalized_forms.py list [--min 2] [--status candidat]
    python tools/review_vocalized_forms.py review [--min 2]          # interactif
    python tools/review_vocalized_forms.py set valide كتب كَتَب
    python tools/review_vocalized_forms.py export formes.json [--min 2]
    python tools/review_vocalized_forms.py import formes.json

`export` écrit les candidates dans un fichier JSON à relire hors du terminal
(champ `status` de chaque forme : `valide`, `signale` ou `candidat`) ; `import`
applique ce fichier. Un mot peut avoir plusieurs vocalisations justes (كَتَبَ
« il a écrit », كُتُب « des livres ») : validez-les toutes, sinon les autres
seront signalées comme suspectes.

Base : celle de l'application en développement (data/nwol.db), ou `--db` —
pour l'application installée, le dossier de données de l'OS (voir le rapport
18, § 17). À lancer application fermée : SQLite n'a qu'un écrivain.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nwol"))

LANGUAGE = "arabe"
STATUSES = ("valide", "signale", "candidat")


def _use_db(path: str | None) -> None:
    import db

    if path:
        db.close_connection()
        db.DB_PATH = str(Path(path).expanduser().resolve())
    from db.schema import initialize_schema

    initialize_schema()


def grouped(min_occurrences: int = 1, status: str | None = None) -> list[dict]:
    """Formes regroupées par mot nu, les mots les plus fréquents d'abord :
    [{"bare", "forms": [{"stem", "status", "occurrences", "reports", "translit"}]}]."""
    from db import lang_episode_db as store
    from services.lang_arabic import transliterate_word

    groups: dict[str, dict] = {}
    for row in store.list_vocalized_forms(LANGUAGE, status=status, min_occurrences=min_occurrences):
        group = groups.setdefault(row["bare"], {"bare": row["bare"], "forms": []})
        group["forms"].append({
            "stem": row["stem_vocalized"], "status": row["status"], "occurrences": row["occurrences"],
            "reports": row["reports"], "translit": transliterate_word(row["stem_vocalized"]),
        })
    return list(groups.values())


def set_status(bare: str, stem: str, status: str) -> None:
    from db import lang_episode_db as store

    if status not in STATUSES:
        raise SystemExit(f"statut inconnu : {status} ({', '.join(STATUSES)})")
    store.set_vocalized_status(LANGUAGE, bare, stem, status)


def export(path: Path, min_occurrences: int = 1) -> int:
    groups = grouped(min_occurrences)
    path.write_text(json.dumps({"language": LANGUAGE, "words": groups}, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return sum(len(g["forms"]) for g in groups)


def import_file(path: Path) -> int:
    """Applique les statuts d'un fichier `export` relu ; renvoie le nombre de
    formes dont le statut a été écrit."""
    data = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for group in data.get("words") or []:
        for form in group.get("forms") or []:
            if form.get("status") in STATUSES:
                set_status(group["bare"], form["stem"], form["status"])
                count += 1
    return count


def _print_group(group: dict) -> None:
    print(f"\n{group['bare']}")
    for i, f in enumerate(group["forms"], start=1):
        flags = f" · {f['reports']} signalement(s)" if f["reports"] else ""
        print(f"  {i}. {f['stem']:<14} {f['translit']:<14} {f['status']:<9} ×{f['occurrences']}{flags}")


def review(min_occurrences: int) -> None:
    print("Pour chaque mot : numéros des formes justes (ex. « 1,3 »), « s 2 » pour signaler la forme 2,\n"
          "Entrée pour passer, « q » pour quitter.")
    for group in grouped(min_occurrences, status=None):
        if not any(f["status"] == "candidat" for f in group["forms"]):
            continue
        _print_group(group)
        answer = input("> ").strip()
        if answer == "q":
            return
        if not answer:
            continue
        if answer.startswith("s "):
            picks, status = answer[2:], "signale"
        else:
            picks, status = answer, "valide"
        for part in picks.replace(" ", "").split(","):
            if part.isdigit() and 1 <= int(part) <= len(group["forms"]):
                set_status(group["bare"], group["forms"][int(part) - 1]["stem"], status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Relecture des vocalisations arabes (A7).")
    parser.add_argument("--db", help="base SQLite (défaut : celle de l'application en développement)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list")
    p_list.add_argument("--min", type=int, default=1)
    p_list.add_argument("--status", choices=STATUSES)
    p_review = sub.add_parser("review")
    p_review.add_argument("--min", type=int, default=1)
    p_set = sub.add_parser("set")
    p_set.add_argument("status", choices=STATUSES)
    p_set.add_argument("bare")
    p_set.add_argument("stem")
    p_export = sub.add_parser("export")
    p_export.add_argument("path")
    p_export.add_argument("--min", type=int, default=1)
    p_import = sub.add_parser("import")
    p_import.add_argument("path")
    args = parser.parse_args(argv)

    _use_db(args.db)
    if args.command == "list":
        groups = grouped(args.min, args.status)
        for group in groups:
            _print_group(group)
        print(f"\n{len(groups)} mot(s)")
    elif args.command == "review":
        review(args.min)
    elif args.command == "set":
        set_status(args.bare, args.stem, args.status)
    elif args.command == "export":
        print(f"{export(Path(args.path), args.min)} forme(s) écrites dans {args.path}")
    elif args.command == "import":
        print(f"{import_file(Path(args.path))} statut(s) appliqué(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
