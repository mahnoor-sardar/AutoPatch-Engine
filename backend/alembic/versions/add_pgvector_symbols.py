"""add native pgvector symbol embeddings

Revision ID: add_pgvector_symbols
Revises: add_pipeline_stage
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op


revision: str = "add_pgvector_symbols"
down_revision: Union[str, Sequence[str], None] = "add_pipeline_stage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.services.embeddings import ensure_pgvector

    ensure_pgvector(op.get_bind())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS symbol_vectors")
    op.execute("DROP EXTENSION IF EXISTS vector")
