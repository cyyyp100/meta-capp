#!/usr/bin/env python
"""Régénère `nwol/db/schema_reference.sql` — la forme RÉELLE de la base.

Pourquoi ce fichier existe : `db/schema.py` crée une base *incomplète*, que les
25 pas de `db/migrations.py` complètent ensuite. Lire `schema.py` seul donne donc
une image fausse du modèle de données — il faudrait rejouer les migrations de
tête. Ce dump est la référence lisible, posée à côté de `schema.py` et
`migrations.py` pour être trouvée par qui cherche le modèle de données ; il est
versionné, et `tests/test_schema_reference.py` échoue s'il n'est plus à jour.

    conda activate nwol && python scripts/dump_schema.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

NWOL_DIR = Path(__file__).resolve().parents[1] / "nwol"
if str(NWOL_DIR) not in sys.path:
    sys.path.insert(0, str(NWOL_DIR))

OUTPUT = NWOL_DIR / "db" / "schema_reference.sql"

# Tables créées par une migration mais qu'aucun code de cette édition ne lit ni
# n'écrit. Elles sont conservées parce qu'une migration ne se réécrit pas : une
# base existante doit rester rejouable de bout en bout.
TABLES_SANS_CODE = ("app_settings", "llm_pdf_cache", "ocr_pages")


def dump_schema() -> str:
    """Schéma d'une base neuve entièrement migrée, trié pour être diffable."""
    import db
    from config.settings import DB_SCHEMA_VERSION

    with tempfile.TemporaryDirectory() as tmp:
        db.close_connection()
        original = db.DB_PATH
        db.DB_PATH = str(Path(tmp) / "schema_ref.db")
        try:
            from db.schema import initialize_schema

            initialize_schema()
            conn = db.get_connection()
            rows = conn.execute(
                """SELECT type, name, tbl_name, sql FROM sqlite_master
                   WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
                   ORDER BY tbl_name, type DESC, name"""
            ).fetchall()
            statements = [f"{(r['sql'] or '').strip()};" for r in rows]
        finally:
            db.close_connection()
            db.DB_PATH = original

    header = [
        "-- Schéma de référence de Meta-Capp — GÉNÉRÉ, ne pas éditer à la main.",
        "--",
        "-- Forme réelle d'une base neuve après application des migrations",
        f"-- (config.settings.DB_SCHEMA_VERSION = {DB_SCHEMA_VERSION}).",
        "-- Régénérer avec :  python scripts/dump_schema.py",
        "--",
        "-- Tables créées par une migration mais sans code lecteur ni écrivain",
        f"-- dans cette édition : {', '.join(TABLES_SANS_CODE)}.",
        "",
    ]
    return "\n".join(header + statements) + "\n"


def main() -> int:
    content = dump_schema()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    changed = not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"{'Mis à jour' if changed else 'Inchangé'} : {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
