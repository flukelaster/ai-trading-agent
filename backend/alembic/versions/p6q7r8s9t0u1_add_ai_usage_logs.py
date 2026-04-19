"""add ai_usage_logs table

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-04-17 03:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p6q7r8s9t0u1"
down_revision: str | None = "o5p6q7r8s9t0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: the table + indexes may already exist from lifespan bootstrap
    # on older deploys that ran before this migration.
    op.execute("SET lock_timeout = '30s'")
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "ai_usage_logs" not in inspector.get_table_names():
        op.create_table(
            "ai_usage_logs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("agent_id", sa.String(100), nullable=False),
            sa.Column("model", sa.String(100), nullable=False),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_usd_sdk", sa.Float(), nullable=True),
            sa.Column("cost_usd_calc", sa.Float(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("turns", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("raw_usage", sa.JSON(), nullable=True),
        )

    indexes = {i["name"] for i in inspector.get_indexes("ai_usage_logs")} if "ai_usage_logs" in inspector.get_table_names() else set()
    if "ix_ai_usage_logs_timestamp" not in indexes:
        op.create_index("ix_ai_usage_logs_timestamp", "ai_usage_logs", ["timestamp"])
    if "ix_ai_usage_logs_agent_id" not in indexes:
        op.create_index("ix_ai_usage_logs_agent_id", "ai_usage_logs", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_logs_agent_id", "ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_timestamp", "ai_usage_logs")
    op.drop_table("ai_usage_logs")
