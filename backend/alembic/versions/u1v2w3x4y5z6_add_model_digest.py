"""add ml_model_logs.model_digest for HMAC integrity check

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-05-03 13:00:00.000000

Adds a nullable HMAC-SHA256 hex column populated at training time and verified
before joblib.load(). Existing rows have NULL digests; the loader rejects them
unless ``ML_DIGEST_REQUIRED=0`` is set during a one-time grace period so an
operator can re-train without simultaneously losing all models.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "u1v2w3x4y5z6"
down_revision: str | None = "t0u1v2w3x4y5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ml_model_logs",
        sa.Column("model_digest", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ml_model_logs", "model_digest")
