"""add model_binary column to ml_model_logs

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-04-09 00:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ml_model_logs', sa.Column('model_binary', sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column('ml_model_logs', 'model_binary')
