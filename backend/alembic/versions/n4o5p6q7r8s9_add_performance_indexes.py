"""add performance indexes on trades, bot_events, news_sentiments

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-04-15 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n4o5p6q7r8s9"
down_revision: str | None = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = [
    ("ix_trades_open_time", "trades", ["open_time"]),
    ("ix_trades_close_time", "trades", ["close_time"]),
    ("ix_trades_symbol_open_time", "trades", ["symbol", "open_time"]),
    ("ix_bot_events_created_at", "bot_events", ["created_at"]),
    ("ix_news_sentiments_created_at", "news_sentiments", ["created_at"]),
]


def upgrade() -> None:
    # Idempotent: tolerate indexes already created out-of-band (manual SQL,
    # earlier deploy, etc.) so reruns don't fail.
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    for name, table, cols in _INDEXES:
        existing = {i["name"] for i in inspector.get_indexes(table)}
        if name not in existing:
            op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table)
