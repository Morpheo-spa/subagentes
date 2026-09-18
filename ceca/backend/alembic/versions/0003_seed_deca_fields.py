"""Seed the DECA field catalogue from app/i18n/deca_fields.json.

The list is never duplicated here: which fields the law demands is data, and the
JSON file is its single source. Idempotent.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-18
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "app" / "i18n" / "deca_fields.json"

definitions_table = sa.table(
    "deca_field_definitions",
    sa.column("code", sa.String),
    sa.column("label_es", sa.String),
    sa.column("label_en", sa.String),
    sa.column("help_es", sa.Text),
    sa.column("help_en", sa.Text),
    sa.column("data_type", sa.String),
    sa.column("is_required", sa.Boolean),
    sa.column("max_length", sa.Integer),
    sa.column("pattern", sa.String),
    sa.column("choices", sa.Text),
    sa.column("legal_reference", sa.String),
    sa.column("sort_order", sa.Integer),
    sa.column("is_active", sa.Boolean),
    sa.column("catalog_version", sa.Integer),
)


def _load_catalogue() -> tuple[int, list[dict[str, Any]]]:
    with CATALOGUE_PATH.open(encoding="utf-8") as handle:
        catalogue = json.load(handle)
    return catalogue["catalog_version"], catalogue["fields"]


def _as_row(field: dict[str, Any], catalog_version: int) -> dict[str, Any]:
    choices = field.get("choices")
    return {
        "code": field["code"],
        "label_es": field["label_es"],
        "label_en": field["label_en"],
        "help_es": field.get("help_es"),
        "help_en": field.get("help_en"),
        "data_type": field.get("data_type", "string"),
        "is_required": bool(field.get("is_required", True)),
        "max_length": field.get("max_length"),
        "pattern": field.get("pattern"),
        "choices": json.dumps(choices, ensure_ascii=False) if choices else None,
        "legal_reference": field.get("legal_reference"),
        "sort_order": field.get("sort_order", 0),
        "is_active": bool(field.get("is_active", True)),
        "catalog_version": catalog_version,
    }


def upgrade() -> None:
    catalog_version, fields = _load_catalogue()
    rows = [_as_row(field, catalog_version) for field in fields]
    statement = postgresql.insert(definitions_table).values(rows)
    op.execute(statement.on_conflict_do_nothing(index_elements=["code"]))


def downgrade() -> None:
    _, fields = _load_catalogue()
    codes = [field["code"] for field in fields]
    op.execute(definitions_table.delete().where(definitions_table.c.code.in_(codes)))
