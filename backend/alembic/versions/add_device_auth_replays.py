"""one-time device OTP/token fingerprints

Revision ID: add_device_auth_replays
Revises: add_audit_event_fields
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_device_auth_replays"
down_revision: Union[str, Sequence[str], None] = "add_audit_event_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_auth_replays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("action_key", sa.String(length=256), nullable=False),
        sa.Column("credential_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "device_id",
            "action_key",
            "credential_hash",
            name="uq_device_auth_replay",
        ),
    )
    op.create_index(
        "ix_device_auth_replays_device_id",
        "device_auth_replays",
        ["device_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_device_auth_replays_device_id", table_name="device_auth_replays")
    op.drop_table("device_auth_replays")
