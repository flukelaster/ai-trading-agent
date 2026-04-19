"""add symbol_configs table

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-04-19 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q7r8s9t0u1v2"
down_revision: str | None = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed defaults mirror SYMBOL_PROFILES in app/config.py as of this migration.
_SEED_ROWS = [
    {
        "symbol": "GOLD",
        "display_name": "Gold (XAUUSD)",
        "broker_alias": "GOLDmicro",
        "is_enabled": True,
        "default_timeframe": "M15",
        "pip_value": 1.0,
        "default_lot": 0.1,
        "max_lot": 1.0,
        "price_decimals": 2,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
        "contract_size": 100,
        "ml_tp_pips": 10.0,
        "ml_sl_pips": 10.0,
        "ml_forward_bars": 10,
        "ml_timeframe": "M15",
    },
    {
        "symbol": "OILCash",
        "display_name": "WTI Oil",
        "broker_alias": "OILCashmicro",
        "is_enabled": False,
        "default_timeframe": "M15",
        "pip_value": 10.0,
        "default_lot": 0.1,
        "max_lot": 5.0,
        "price_decimals": 2,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
        "contract_size": 100,
        "ml_tp_pips": 0.5,
        "ml_sl_pips": 0.5,
        "ml_forward_bars": 10,
        "ml_timeframe": "M15",
    },
    {
        "symbol": "BTCUSD",
        "display_name": "Bitcoin",
        "broker_alias": "BTCUSDmicro",
        "is_enabled": False,
        "default_timeframe": "M15",
        "pip_value": 1.0,
        "default_lot": 0.01,
        "max_lot": 0.5,
        "price_decimals": 2,
        "sl_atr_mult": 2.0,
        "tp_atr_mult": 3.0,
        "contract_size": 1,
        "ml_tp_pips": 500.0,
        "ml_sl_pips": 500.0,
        "ml_forward_bars": 5,
        "ml_timeframe": "H1",
    },
    {
        "symbol": "USDJPY",
        "display_name": "USD/JPY",
        "broker_alias": "USDJPYmicro",
        "is_enabled": False,
        "default_timeframe": "M15",
        "pip_value": 100.0,
        "default_lot": 0.1,
        "max_lot": 5.0,
        "price_decimals": 3,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
        "contract_size": 100000,
        "ml_tp_pips": 0.3,
        "ml_sl_pips": 0.3,
        "ml_forward_bars": 10,
        "ml_timeframe": "M15",
    },
]


def upgrade() -> None:
    op.execute("SET lock_timeout = '30s'")
    op.create_table(
        "symbol_configs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("broker_alias", sa.String(32), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("default_timeframe", sa.String(8), nullable=False, server_default="M15"),
        sa.Column("pip_value", sa.Float(), nullable=False),
        sa.Column("default_lot", sa.Float(), nullable=False),
        sa.Column("max_lot", sa.Float(), nullable=False),
        sa.Column("price_decimals", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("sl_atr_mult", sa.Float(), nullable=False, server_default="1.5"),
        sa.Column("tp_atr_mult", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("contract_size", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("ml_tp_pips", sa.Float(), nullable=False),
        sa.Column("ml_sl_pips", sa.Float(), nullable=False),
        sa.Column("ml_forward_bars", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("ml_timeframe", sa.String(8), nullable=False, server_default="M15"),
        sa.Column("ml_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("ml_last_trained_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
        sa.UniqueConstraint("symbol", name="uq_symbol_configs_symbol"),
    )
    op.create_index("ix_symbol_configs_symbol", "symbol_configs", ["symbol"])

    bind = op.get_bind()
    table = sa.table(
        "symbol_configs",
        sa.column("symbol", sa.String),
        sa.column("display_name", sa.String),
        sa.column("broker_alias", sa.String),
        sa.column("is_enabled", sa.Boolean),
        sa.column("default_timeframe", sa.String),
        sa.column("pip_value", sa.Float),
        sa.column("default_lot", sa.Float),
        sa.column("max_lot", sa.Float),
        sa.column("price_decimals", sa.Integer),
        sa.column("sl_atr_mult", sa.Float),
        sa.column("tp_atr_mult", sa.Float),
        sa.column("contract_size", sa.Float),
        sa.column("ml_tp_pips", sa.Float),
        sa.column("ml_sl_pips", sa.Float),
        sa.column("ml_forward_bars", sa.Integer),
        sa.column("ml_timeframe", sa.String),
    )
    bind.execute(table.insert(), _SEED_ROWS)


def downgrade() -> None:
    op.drop_index("ix_symbol_configs_symbol", "symbol_configs")
    op.drop_table("symbol_configs")
