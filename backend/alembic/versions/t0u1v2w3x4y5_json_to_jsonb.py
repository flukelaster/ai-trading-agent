"""convert JSON columns to JSONB

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2026-05-03 12:30:00.000000

PostgreSQL ``JSON`` stores raw text and re-parses on every read; ``JSONB`` stores
a parsed binary representation, supports GIN indexing, and is faster for reads.

Affected columns:
- audit_logs.detail
- trades.pre_trade_snapshot
- trades.post_trade_analysis
- runners.tags, runners.resource_limits
- runner_jobs.input, runner_jobs.output
- agent_memory.evidence
- ai_usage_logs.raw_usage

Each ``ALTER COLUMN ... TYPE jsonb USING col::jsonb`` takes an
``ACCESS EXCLUSIVE`` lock for the duration of the rewrite. Run during a
maintenance window. Safe on empty / small tables; multi-GB tables may need
``pg_repack`` instead.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "t0u1v2w3x4y5"
down_revision: str | None = "s9t0u1v2w3x4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_JSONB_TARGETS = [
    ("audit_logs", "detail"),
    ("trades", "pre_trade_snapshot"),
    ("trades", "post_trade_analysis"),
    ("runners", "tags"),
    ("runners", "resource_limits"),
    ("runner_jobs", "input"),
    ("runner_jobs", "output"),
    ("agent_memory", "evidence"),
    ("ai_usage_logs", "raw_usage"),
]


def upgrade() -> None:
    for table, column in _JSONB_TARGETS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE jsonb USING {column}::jsonb")


def downgrade() -> None:
    for table, column in _JSONB_TARGETS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE json USING {column}::json")
