"""add expected_price to trades for slippage tracking

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-04-11 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trades', sa.Column('expected_price', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('trades', 'expected_price')
