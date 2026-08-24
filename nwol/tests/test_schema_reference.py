"""`nwol/db/schema_reference.sql` doit décrire la base réelle (§ B6).

`db/schema.py` crée une base incomplète que 25 pas de migration complètent : lire
`schema.py` seul donne une image fausse du modèle de données. Le dump de
référence est la documentation exacte — encore faut-il qu'elle ne dérive pas.
Ce test échoue dès qu'une migration est ajoutée sans régénérer le fichier.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO_ROOT / "nwol" / "db" / "schema_reference.sql"
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _dump_schema(monkeypatch, tmp_path) -> str:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import db

    db.close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ref.db"))
    from dump_schema import dump_schema

    try:
        return dump_schema()
    finally:
        db.close_connection()


def test_reference_schema_matches_a_freshly_migrated_database(monkeypatch, tmp_path):
    assert SCHEMA_SQL.exists(), "schema_reference.sql absent : python scripts/dump_schema.py"
    attendu = _dump_schema(monkeypatch, tmp_path)
    actuel = SCHEMA_SQL.read_text(encoding="utf-8")
    assert actuel == attendu, (
        "nwol/db/schema_reference.sql ne décrit plus la base réelle.\n"
        "Régénérer :  python scripts/dump_schema.py"
    )


def test_reference_schema_covers_every_table_of_the_live_database(monkeypatch, tmp_path):
    """Garde-fou indépendant du format du dump : aucune table ne doit manquer."""
    import db

    db.close_connection()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "live.db"))
    from db.schema import initialize_schema

    initialize_schema()
    tables = {
        row["name"]
        for row in db.get_connection().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    db.close_connection()

    reference = SCHEMA_SQL.read_text(encoding="utf-8")
    manquantes = sorted(t for t in tables if f"CREATE TABLE {t} " not in reference)
    assert not manquantes, f"tables absentes de schema_reference.sql : {manquantes}"


@pytest.mark.parametrize("table", ("app_settings", "llm_pdf_cache", "ocr_pages"))
def test_tables_without_code_are_documented_as_such(table):
    """Ces tables existent en base et aucun code de cette édition ne les touche.
    Un nouveau venu doit l'apprendre du fichier, pas d'un grep infructueux."""
    reference = SCHEMA_SQL.read_text(encoding="utf-8")
    entete = reference.split("CREATE TABLE", 1)[0]
    assert table in entete, f"{table} n'est pas signalée comme table sans code"
