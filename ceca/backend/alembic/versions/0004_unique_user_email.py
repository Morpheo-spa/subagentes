"""Make ``users.email`` unique across the whole installation.

The login has no tenant to scope its lookup by, so the address has to identify
one person and only one. While uniqueness was per company, any administrator
could register a rival company's administrator address in their own company and
turn that person's login into a permanent 500 (docs/SECURITY-AUDIT.md E-08).

Idempotent: re-running finds the index already there and does nothing. If the
data cannot satisfy the constraint the migration **refuses to start** and names
the offending addresses, rather than failing halfway through with a bare
``UniqueViolation``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_users_email"
TABLE_NAME = "users"

DUPLICATES = sa.text(
    """
    SELECT email, count(*) AS total
    FROM users
    GROUP BY email
    HAVING count(*) > 1
    ORDER BY total DESC, email
    """
)


def _index_exists(connection: sa.Connection) -> bool:
    inspector = sa.inspect(connection)
    return any(index["name"] == INDEX_NAME for index in inspector.get_indexes(TABLE_NAME))


def _reject_duplicates(connection: sa.Connection) -> None:
    rows = connection.execute(DUPLICATES).all()
    if not rows:
        return
    listed = ", ".join(f"{email} (x{total})" for email, total in rows[:20])
    raise RuntimeError(
        "Cannot make users.email unique: "
        f"{len(rows)} address(es) are used by more than one user: {listed}. "
        "Resolve them first — rename or deactivate the duplicates, keeping the "
        "account that actually signs in — then run this migration again. "
        "Nothing has been changed."
    )


def upgrade() -> None:
    connection = op.get_bind()
    if _index_exists(connection):
        return
    _reject_duplicates(connection)
    op.create_index(INDEX_NAME, TABLE_NAME, ["email"], unique=True)


def downgrade() -> None:
    connection = op.get_bind()
    if not _index_exists(connection):
        return
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
