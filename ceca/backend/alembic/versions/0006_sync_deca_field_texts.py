"""Bring the user-facing texts of the DECA catalogue back in line with the JSON.

0003 seeds ``deca_field_definitions`` from ``app/i18n/deca_fields.json`` with
``ON CONFLICT DO NOTHING``, so a database migrated before that file changed
keeps whatever it was seeded with. The ``observaciones`` row carried a
development note in its help text and legal reference ("pendiente de
contrastar", "ver docs/DECA.md") that the form showed to every user; the doubt
itself still lives in ``docs/DECA.md``, which is where it belongs.

This migration UPDATEs, per ``code`` already in the table, the five columns a
person reads: ``label_es``, ``label_en``, ``help_es``, ``help_en`` and
``legal_reference``. Nothing else moves: ``is_required``, ``data_type``,
``pattern``, ``choices`` and ``max_length`` decide validation and are left
alone, and a code absent from the table is not inserted (that is 0003's job).
The list of codes is never written here: the JSON file is its single source.

Idempotent: re-running writes the same values again.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-18
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.sql.dml import Update

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "app" / "i18n" / "deca_fields.json"

#: The columns this migration owns. Everything that decides validation stays out.
TEXT_COLUMNS = ("label_es", "label_en", "help_es", "help_en", "legal_reference")

definitions_table = sa.table(
    "deca_field_definitions",
    sa.column("code", sa.String),
    sa.column("label_es", sa.String),
    sa.column("label_en", sa.String),
    sa.column("help_es", sa.Text),
    sa.column("help_en", sa.Text),
    sa.column("legal_reference", sa.String),
)


def texts_by_code() -> dict[str, dict[str, Any]]:
    """What the JSON says each code should read. ``None`` clears a column."""
    with CATALOGUE_PATH.open(encoding="utf-8") as handle:
        fields: list[dict[str, Any]] = json.load(handle)["fields"]
    return {
        field["code"]: {column: field.get(column) for column in TEXT_COLUMNS} for field in fields
    }


def statements() -> list[Update]:
    """One UPDATE per code. A code the table does not hold matches no row."""
    return [
        definitions_table.update().where(definitions_table.c.code == code).values(**values)
        for code, values in texts_by_code().items()
    ]


def upgrade() -> None:
    for statement in statements():
        op.execute(statement)


def downgrade() -> None:
    """Deliberately nothing.

    The texts this migration replaces were development notes shown to users by
    mistake, and there is no earlier source to restore them from: 0003 reads the
    same JSON file as this migration, at whatever revision of the code is
    running, so "the previous text" is not recoverable from the repository
    state a downgrade runs in. Reverting the schema is not affected - no column
    or row is added or removed here - and a downgrade past 0003 still deletes
    the rows as before.
    """
