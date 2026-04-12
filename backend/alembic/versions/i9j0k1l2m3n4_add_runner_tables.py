"""add runner tables for Docker sandbox runner system

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-04-12 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Runners table
    op.create_table(
        'runners',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('container_id', sa.String(64), nullable=True),
        sa.Column('image', sa.String(200), nullable=False),
        sa.Column('status', sa.Enum('stopped', 'starting', 'online', 'degraded', 'error', name='runnerstatus'), server_default='stopped', nullable=False),
        sa.Column('max_concurrent_jobs', sa.Integer(), server_default='3', nullable=False),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('resource_limits', sa.JSON(), nullable=True),
        sa.Column('last_heartbeat_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # Runner jobs table
    op.create_table(
        'runner_jobs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('runner_id', sa.BigInteger(), nullable=True),
        sa.Column('job_type', sa.String(50), nullable=False),
        sa.Column('status', sa.Enum('pending', 'running', 'completed', 'failed', 'cancelled', name='jobstatus'), server_default='pending', nullable=False),
        sa.Column('input', sa.JSON(), nullable=True),
        sa.Column('output', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_runner_jobs_status', 'runner_jobs', ['status'])
    op.create_index('idx_runner_jobs_runner_id', 'runner_jobs', ['runner_id'])

    # Runner logs table
    op.create_table(
        'runner_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('runner_id', sa.BigInteger(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('level', sa.String(10), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_runner_logs_runner_id', 'runner_logs', ['runner_id'])
    op.create_index('idx_runner_logs_timestamp', 'runner_logs', ['timestamp'])

    # Runner metrics table
    op.create_table(
        'runner_metrics',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('runner_id', sa.BigInteger(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('cpu_percent', sa.Float(), nullable=True),
        sa.Column('memory_mb', sa.Float(), nullable=True),
        sa.Column('memory_limit_mb', sa.Float(), nullable=True),
        sa.Column('network_rx_bytes', sa.BigInteger(), nullable=True),
        sa.Column('network_tx_bytes', sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_runner_metrics_runner_id', 'runner_metrics', ['runner_id'])
    op.create_index('idx_runner_metrics_timestamp', 'runner_metrics', ['timestamp'])


def downgrade() -> None:
    op.drop_index('idx_runner_metrics_timestamp', table_name='runner_metrics')
    op.drop_index('idx_runner_metrics_runner_id', table_name='runner_metrics')
    op.drop_table('runner_metrics')

    op.drop_index('idx_runner_logs_timestamp', table_name='runner_logs')
    op.drop_index('idx_runner_logs_runner_id', table_name='runner_logs')
    op.drop_table('runner_logs')

    op.drop_index('idx_runner_jobs_runner_id', table_name='runner_jobs')
    op.drop_index('idx_runner_jobs_status', table_name='runner_jobs')
    op.drop_table('runner_jobs')

    op.drop_table('runners')
    op.execute("DROP TYPE IF EXISTS jobstatus")
    op.execute("DROP TYPE IF EXISTS runnerstatus")
