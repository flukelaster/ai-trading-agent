"""add performance + soft-delete + foreign-key indexes

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-05-03 12:00:00.000000

Adds composite + partial indexes flagged by the production audit:
- ``ix_trades_symbol_close_time`` — daily summary queries filter on both columns
- ``ix_runner_logs_runner_id`` — runner observability reads
- ``ix_runner_metrics_runner_id`` — runner metrics reads
- ``ix_runner_jobs_runner_id`` — job queue lookups
- ``ix_secrets_active`` — partial index on ``key`` WHERE not deleted
- ``ix_symbol_configs_active`` — partial index on ``symbol`` WHERE not deleted
- ``ix_audit_logs_created_at`` — time-range scans
- ``ix_audit_logs_action_created`` — composite for ``WHERE action=? AND created_at>=?``
- ``ix_ohlcv_data_symbol_tf_time`` — composite covering load_from_db filter

Uses ``IF NOT EXISTS`` so re-running on a partially-applied DB is safe.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "s9t0u1v2w3x4"
down_revision: str | None = "r8s9t0u1v2w3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = [
    (
        "ix_trades_symbol_close_time",
        "CREATE INDEX IF NOT EXISTS ix_trades_symbol_close_time "
        "ON trades (symbol, close_time) WHERE is_archived = false",
    ),
    (
        "ix_runner_logs_runner_id",
        "CREATE INDEX IF NOT EXISTS ix_runner_logs_runner_id ON runner_logs (runner_id)",
    ),
    (
        "ix_runner_metrics_runner_id",
        "CREATE INDEX IF NOT EXISTS ix_runner_metrics_runner_id ON runner_metrics (runner_id)",
    ),
    (
        "ix_runner_jobs_runner_id",
        "CREATE INDEX IF NOT EXISTS ix_runner_jobs_runner_id ON runner_jobs (runner_id)",
    ),
    (
        "ix_secrets_active",
        "CREATE INDEX IF NOT EXISTS ix_secrets_active ON secrets (key) WHERE is_deleted = false",
    ),
    (
        "ix_symbol_configs_active",
        "CREATE INDEX IF NOT EXISTS ix_symbol_configs_active "
        "ON symbol_configs (symbol) WHERE is_deleted = false",
    ),
    (
        "ix_audit_logs_created_at",
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at)",
    ),
    (
        "ix_audit_logs_action_created",
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_action_created ON audit_logs (action, created_at)",
    ),
    (
        "ix_ohlcv_data_symbol_tf_time",
        "CREATE INDEX IF NOT EXISTS ix_ohlcv_data_symbol_tf_time "
        "ON ohlcv_data (symbol, timeframe, time DESC)",
    ),
]


def upgrade() -> None:
    for _, sql in _INDEXES:
        op.execute(sql)


def downgrade() -> None:
    for name, _ in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
