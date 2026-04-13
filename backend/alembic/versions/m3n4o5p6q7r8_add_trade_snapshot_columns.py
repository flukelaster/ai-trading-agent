"""add trade_reason, pre_trade_snapshot, post_trade_analysis to trades

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-04-13 21:26:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'm3n4o5p6q7r8'
down_revision: Union[str, None] = 'l2m3n4o5p6q7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [c['name'] for c in inspector.get_columns('trades')]

    if 'trade_reason' not in existing:
        op.add_column('trades', sa.Column('trade_reason', sa.String(255), nullable=True))
    if 'pre_trade_snapshot' not in existing:
        op.add_column('trades', sa.Column('pre_trade_snapshot', sa.JSON(), nullable=True))
    if 'post_trade_analysis' not in existing:
        op.add_column('trades', sa.Column('post_trade_analysis', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('trades', 'post_trade_analysis')
    op.drop_column('trades', 'pre_trade_snapshot')
    op.drop_column('trades', 'trade_reason')
