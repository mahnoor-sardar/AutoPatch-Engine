"""add pipeline stage to sandbox runs

Revision ID: add_pipeline_stage
Revises: add_pipeline_controls
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_pipeline_stage"
down_revision: Union[str, Sequence[str], None] = "add_pipeline_controls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sandbox_runs",
        sa.Column(
            "pipeline_stage",
            sa.String(length=32),
            nullable=False,
            server_default="provision",
        ),
    )


def downgrade() -> None:
    op.drop_column("sandbox_runs", "pipeline_stage")
