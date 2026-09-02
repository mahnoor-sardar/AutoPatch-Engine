"""add llm token usage to sandbox runs

Revision ID: add_llm_tokens_used
Revises: add_device_auth_replays
Create Date: 2026-09-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_llm_tokens_used"
down_revision: Union[str, Sequence[str], None] = "add_device_auth_replays"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sandbox_runs",
        sa.Column(
            "llm_tokens_used",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("sandbox_runs", "llm_tokens_used")
