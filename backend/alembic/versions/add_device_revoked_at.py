"""add device revoked_at for lost-device revocation

Revision ID: add_device_revoked_at
Revises: add_llm_tokens_used
Create Date: 2026-09-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_device_revoked_at"
down_revision: Union[str, Sequence[str], None] = "add_llm_tokens_used"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("devices", "revoked_at")
