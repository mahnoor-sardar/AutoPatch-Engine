"""add sandbox_runs.source_sha for verified git commit binding

Revision ID: add_sandbox_run_source_sha
Revises: add_device_revoked_at
Create Date: 2026-09-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_sandbox_run_source_sha"
down_revision: Union[str, Sequence[str], None] = "add_device_revoked_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sandbox_runs",
        sa.Column("source_sha", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sandbox_runs", "source_sha")
