"""add sandbox_runs stage owner token and lease expiry

Revision ID: add_sandbox_run_stage_lease
Revises: add_sandbox_run_source_sha
Create Date: 2026-09-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_sandbox_run_stage_lease"
down_revision: Union[str, Sequence[str], None] = "add_sandbox_run_source_sha"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sandbox_runs",
        sa.Column("stage_owner_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "sandbox_runs",
        sa.Column(
            "stage_lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sandbox_runs", "stage_lease_expires_at")
    op.drop_column("sandbox_runs", "stage_owner_token")
