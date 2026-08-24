from alembic import op
import sqlalchemy as sa


revision = "88e02ab53e15"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "github_installations",
        "installation_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )

    op.alter_column(
        "repositories",
        "installation_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "repositories",
        "installation_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )

    op.alter_column(
        "github_installations",
        "installation_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )