"""Record every Stripe event by its id, so a replayed webhook is not processed twice.

``stripe.Webhook.construct_event`` verifies the signature and a 300 s tolerance,
but nothing remembered which events had already been applied: a retried or a
captured-and-resent delivery ran the handler again (docs/SECURITY-AUDIT.md E-20).
``billing_events`` is inserted before the handler runs, in the same transaction.

Idempotent: re-running finds the table already there and does nothing.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "billing_events"


def _table_exists(connection: sa.Connection) -> bool:
    return sa.inspect(connection).has_table(TABLE_NAME)


def upgrade() -> None:
    if _table_exists(op.get_bind()):
        return
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=120), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_billing_events"),
    )


def downgrade() -> None:
    if not _table_exists(op.get_bind()):
        return
    op.drop_table(TABLE_NAME)
