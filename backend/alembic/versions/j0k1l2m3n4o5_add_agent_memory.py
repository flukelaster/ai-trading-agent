"""add agent_memories table for layered memory system

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-04-12 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'j0k1l2m3n4o5'
down_revision: Union[str, None] = 'i9j0k1l2m3n4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_memories',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tier', sa.Enum('mid', 'long', name='memorytier'), nullable=False),
        sa.Column('category', sa.Enum('pattern', 'strategy', 'risk', 'regime', 'correlation', name='memorycategory'), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=True),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('hit_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('miss_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_validated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('promoted_at', sa.DateTime(), nullable=True),
        sa.Column('source', sa.String(50), nullable=False, server_default='reflector'),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('content_hash'),
    )
    op.create_index('ix_agent_memories_tier', 'agent_memories', ['tier'])
    op.create_index('ix_agent_memories_category', 'agent_memories', ['category'])
    op.create_index('ix_agent_memories_symbol', 'agent_memories', ['symbol'])


def downgrade() -> None:
    op.drop_index('ix_agent_memories_symbol')
    op.drop_index('ix_agent_memories_category')
    op.drop_index('ix_agent_memories_tier')
    op.drop_table('agent_memories')
    op.execute("DROP TYPE IF EXISTS memorytier")
    op.execute("DROP TYPE IF EXISTS memorycategory")
