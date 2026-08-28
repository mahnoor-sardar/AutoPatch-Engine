"""add structured fields to audit events

Revision ID: add_audit_event_fields
Revises: add_pgvector_symbols
Create Date: 2026-08-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_audit_event_fields"
down_revision: Union[str, Sequence[str], None] = "add_pgvector_symbols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("actor", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column("result", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column("event_metadata", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_events", "event_metadata")
    op.drop_column("audit_events", "result")
    op.drop_column("audit_events", "actor")
