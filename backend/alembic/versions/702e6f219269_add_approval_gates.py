"""add approval gates

Revision ID: 702e6f219269
Revises: 0c2efa1a2a96
Create Date: 2026-08-25 22:16:55.640826

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "702e6f219269"
down_revision: Union[str, Sequence[str], None] = "0c2efa1a2a96"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_gates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("gate", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("device_id", sa.String(length=128), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["sandbox_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_approval_gates_run_id",
        "approval_gates",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_approval_gates_run_id",
        table_name="approval_gates",
    )
    op.drop_table("approval_gates")