"""Seed the commercial plan catalogue.

Idempotent: re-running inserts nothing. A limit of -1 means unlimited.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-18
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNLIMITED = -1

PLANS: tuple[dict[str, Any], ...] = (
    {
        "code": "free",
        "name_es": "Gratuito",
        "name_en": "Free",
        "price_cents": 0,
        "currency": "EUR",
        "interval": "month",
        "limits": {"documents_per_month": 50, "storage_gb": 1, "users": 2, "sites": 1},
        "is_public": True,
        "sort_order": 10,
    },
    {
        "code": "pro",
        "name_es": "Profesional",
        "name_en": "Professional",
        "price_cents": 4900,
        "currency": "EUR",
        "interval": "month",
        "limits": {"documents_per_month": 1000, "storage_gb": 50, "users": 10, "sites": 5},
        "is_public": True,
        "sort_order": 20,
    },
    {
        "code": "business",
        "name_es": "Empresa",
        "name_en": "Business",
        "price_cents": 14900,
        "currency": "EUR",
        "interval": "month",
        "limits": {
            "documents_per_month": UNLIMITED,
            "storage_gb": 200,
            "users": 50,
            "sites": 25,
        },
        "is_public": True,
        "sort_order": 30,
    },
)

plans_table = sa.table(
    "plans",
    sa.column("code", sa.String),
    sa.column("name_es", sa.String),
    sa.column("name_en", sa.String),
    sa.column("price_cents", sa.Integer),
    sa.column("currency", sa.String),
    sa.column("interval", sa.String),
    sa.column("limits", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("is_public", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)


def _as_jsonb(value: dict[str, int]) -> sa.Cast:
    """Render JSON as a cast string literal, so `alembic upgrade --sql` also works."""
    return sa.cast(sa.literal(json.dumps(value), sa.String), postgresql.JSONB())


def upgrade() -> None:
    rows = [plan | {"limits": _as_jsonb(plan["limits"])} for plan in PLANS]
    statement = postgresql.insert(plans_table).values(rows)
    op.execute(statement.on_conflict_do_nothing(index_elements=["code"]))


def downgrade() -> None:
    codes = [plan["code"] for plan in PLANS]
    op.execute(plans_table.delete().where(plans_table.c.code.in_(codes)))
