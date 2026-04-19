"""add asset_class to symbol_configs

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-04-19 17:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r8s9t0u1v2w3"
down_revision: str | None = "q7r8s9t0u1v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Heuristic backfill — used only for rows that already exist.
# Users can edit via the Symbols UI afterwards.
_BACKFILL = [
    ("GOLD", "metal"),
    ("XAUUSD", "metal"),
    ("SILVER", "metal"),
    ("XAGUSD", "metal"),
    ("OIL", "energy"),
    ("OILCash", "energy"),
    ("WTI", "energy"),
    ("BRENT", "energy"),
    ("NATGAS", "energy"),
    ("BTCUSD", "crypto"),
    ("ETHUSD", "crypto"),
    ("SOLUSD", "crypto"),
    ("ENJ", "crypto"),
    ("US100", "index"),
    ("US500", "index"),
    ("US30", "index"),
    ("NAS100", "index"),
    ("SPX500", "index"),
    ("DAX", "index"),
]


def upgrade() -> None:
    # Add column with default "forex" — safe conservative fallback.
    op.add_column(
        "symbol_configs",
        sa.Column(
            "asset_class",
            sa.String(length=16),
            nullable=False,
            server_default="forex",
        ),
    )

    # Backfill known canonical symbols.
    conn = op.get_bind()
    for symbol, cls in _BACKFILL:
        conn.execute(
            sa.text("UPDATE symbol_configs SET asset_class = :cls WHERE symbol = :sym"),
            {"cls": cls, "sym": symbol},
        )


def downgrade() -> None:
    op.drop_column("symbol_configs", "asset_class")
