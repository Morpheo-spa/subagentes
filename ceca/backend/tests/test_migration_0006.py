"""0006 rewrites the catalogue texts a user reads, and nothing else.

The ``observaciones`` row seeded by 0003 carried a development note in its
help text and its legal reference, and the form showed it. The JSON is clean
now; this migration brings an already-migrated database to the same state.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.models.deca import DecaFieldDefinition

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = json.loads((BACKEND_ROOT / "app" / "i18n" / "deca_fields.json").read_text("utf-8"))
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "0006_sync_deca_field_texts.py"

OLD_HELP_ES = (
    "Indicaciones que las partes consideren útiles. "
    "Confianza media sobre su exigibilidad: ver docs/DECA.md."
)
OLD_LEGAL = "Art. 6.g Orden FOM/2861/2012 (pendiente de contrastar)"
INTERNAL_NOTES = ("pendiente de contrastar", "docs/DECA.md", "Confianza", "confidence")


def _migration() -> Any:
    spec = importlib.util.spec_from_file_location("migration_0006", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def stale_catalogue(db: Any) -> None:
    """The table as 0003 left it before the JSON was cleaned."""
    for field in CATALOGUE["fields"]:
        stale = field["code"] == "observaciones"
        db.add(
            DecaFieldDefinition(
                code=field["code"],
                label_es="ETIQUETA VIEJA" if stale else field["label_es"],
                label_en=field["label_en"],
                help_es=OLD_HELP_ES if stale else field.get("help_es"),
                help_en=field.get("help_en"),
                data_type=field["data_type"],
                is_required=field["is_required"],
                max_length=field.get("max_length"),
                pattern=field.get("pattern"),
                legal_reference=OLD_LEGAL if stale else field.get("legal_reference"),
                sort_order=field.get("sort_order", 0),
                is_active=True,
                catalog_version=CATALOGUE["catalog_version"],
            )
        )
    await db.flush()


def test_the_catalogue_no_longer_ships_internal_notes_to_the_form() -> None:
    for field in CATALOGUE["fields"]:
        for column in ("label_es", "label_en", "help_es", "help_en", "legal_reference"):
            text = field.get(column) or ""
            for note in INTERNAL_NOTES:
                assert note not in text, f"{field['code']}.{column} still says {note!r}"


def test_the_migration_is_a_single_head_after_0005() -> None:
    module = _migration()

    assert module.revision == "0006"
    assert module.down_revision == "0005"


async def test_upgrade_syncs_the_five_text_columns_and_nothing_else(
    db: Any, stale_catalogue: None
) -> None:
    module = _migration()
    before = await db.get(DecaFieldDefinition, "observaciones")
    assert before.help_es == OLD_HELP_ES
    original_required, original_type = before.is_required, before.data_type

    for statement in module.statements():
        await db.execute(statement)
    db.expire_all()

    row = await db.get(DecaFieldDefinition, "observaciones")
    wanted = next(f for f in CATALOGUE["fields"] if f["code"] == "observaciones")
    assert row.label_es == wanted["label_es"]
    assert row.help_es == "Indicaciones que las partes consideren útiles."
    assert row.help_en == "Notes the parties consider useful."
    assert row.legal_reference == "Art. 6.g Orden FOM/2861/2012"
    assert row.is_required == original_required
    assert row.data_type == original_type


async def test_upgrade_is_idempotent_and_inserts_nothing(db: Any, stale_catalogue: None) -> None:
    module = _migration()
    (await db.execute(select(DecaFieldDefinition.code))).all()

    for _ in range(2):
        for statement in module.statements():
            await db.execute(statement)
    db.expire_all()

    codes = {row for (row,) in (await db.execute(select(DecaFieldDefinition.code))).all()}
    assert codes == {f["code"] for f in CATALOGUE["fields"]}
    for field in CATALOGUE["fields"]:
        row = await db.get(DecaFieldDefinition, field["code"])
        for column in module.TEXT_COLUMNS:
            assert getattr(row, column) == field.get(column), f"{field['code']}.{column}"


def test_downgrade_is_documented_as_a_no_op() -> None:
    module = _migration()

    assert module.downgrade.__doc__ and "nothing" in module.downgrade.__doc__.lower()
