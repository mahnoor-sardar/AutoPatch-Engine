"""add reproduction attempts

Revision ID: add_reproduction_attempts
Revises: 702e6f219269
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_reproduction_attempts"
down_revision: Union[str, Sequence[str], None] = "702e6f219269"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reproduction_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("stack_trace", sa.Text(), nullable=False),
        sa.Column(
            "diagnostic_path",
            sa.String(length=1024),
            nullable=True,
        ),
        sa.Column(
            "diagnostic_name",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "diagnostic_line",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "test_path",
            sa.String(length=1024),
            nullable=True,
        ),
        sa.Column(
            "test_source",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "exit_code",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "stdout",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "stderr",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "reproduced",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["sandbox_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_reproduction_attempts_run_id",
        "reproduction_attempts",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reproduction_attempts_run_id",
        table_name="reproduction_attempts",
    )
    op.drop_table("reproduction_attempts")