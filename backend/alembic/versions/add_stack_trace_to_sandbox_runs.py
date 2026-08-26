"""add stack trace to sandbox runs

Revision ID: add_stack_trace_to_sandbox_runs
Revises: add_reproduction_attempts
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_stack_trace_to_sandbox_runs"
down_revision: Union[str, Sequence[str], None] = "add_reproduction_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sandbox_runs",
        sa.Column(
            "stack_trace",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "sandbox_runs",
        "stack_trace",
    )