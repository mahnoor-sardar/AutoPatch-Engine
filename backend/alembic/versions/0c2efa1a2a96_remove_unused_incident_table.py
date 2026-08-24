from alembic import op


revision = "0c2efa1a2a96"
down_revision = "88e02ab53e15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("incidents")


def downgrade() -> None:
    from sqlalchemy.dialects import postgresql
    import sqlalchemy as sa

    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )