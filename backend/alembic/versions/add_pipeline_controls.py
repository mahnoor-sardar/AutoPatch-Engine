"""add pipeline controls

Revision ID: add_pipeline_controls
Revises: add_error_ingests
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_pipeline_controls"
down_revision: Union[str, Sequence[str], None] = "add_error_ingests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sandbox_runs",
        sa.Column("current_diff", sa.Text(), nullable=True),
    )
    op.add_column(
        "sandbox_runs",
        sa.Column(
            "patch_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "sandbox_runs",
        sa.Column("pr_url", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "sandbox_runs",
        sa.Column(
            "control_state",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )

    op.add_column(
        "symbols",
        sa.Column("embedding", sa.Text(), nullable=True),
    )
    op.create_index("ix_symbols_run_id", "symbols", ["run_id"])
    op.create_index("ix_symbols_name", "symbols", ["name"])

    op.create_table(
        "patch_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["sandbox_runs.id"]),
    )
    op.create_index(
        "ix_patch_attempts_run_id",
        "patch_attempts",
        ["run_id"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("device_id", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["sandbox_runs.id"]),
    )
    op.create_index("ix_audit_events_run_id", "audit_events", ["run_id"])
    op.create_index(
        "ix_audit_events_device_id",
        "audit_events",
        ["device_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_device_id", table_name="audit_events")
    op.drop_index("ix_audit_events_run_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_patch_attempts_run_id", table_name="patch_attempts")
    op.drop_table("patch_attempts")
    op.drop_index("ix_symbols_name", table_name="symbols")
    op.drop_index("ix_symbols_run_id", table_name="symbols")
    op.drop_column("symbols", "embedding")
    op.drop_column("sandbox_runs", "control_state")
    op.drop_column("sandbox_runs", "pr_url")
    op.drop_column("sandbox_runs", "patch_attempts")
    op.drop_column("sandbox_runs", "current_diff")
