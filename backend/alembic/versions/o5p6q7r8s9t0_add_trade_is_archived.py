"""add is_archived to trades

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-04-17 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o5p6q7r8s9t0"
down_revision: str | None = "n4o5p6q7r8s9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: the column + index may already exist when lifespan schema
    # bootstrap added them on older deploys before this migration ran.
    op.execute("SET lock_timeout = '30s'")
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    columns = {c["name"] for c in inspector.get_columns("trades")}
    if "is_archived" not in columns:
        op.add_column(
            "trades",
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        )

    indexes = {i["name"] for i in inspector.get_indexes("trades")}
    if "ix_trades_is_archived" not in indexes:
        op.create_index("ix_trades_is_archived", "trades", ["is_archived"])


def downgrade() -> None:
    op.drop_index("ix_trades_is_archived", "trades")
    op.drop_column("trades", "is_archived")
