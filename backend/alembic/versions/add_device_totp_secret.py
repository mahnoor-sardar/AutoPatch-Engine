"""add device totp secret

Revision ID: add_device_totp_secret
Revises: add_stack_trace_to_sandbox_runs
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_device_totp_secret"
down_revision: Union[str, Sequence[str], None] = (
    "add_stack_trace_to_sandbox_runs"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "totp_secret",
            sa.String(length=64),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("devices", "totp_secret")
