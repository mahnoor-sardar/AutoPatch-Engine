revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    op.create_table(
        "github_installations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("installation_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("account_login", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(255), nullable=False, unique=True),
        sa.Column("installation_id", sa.Integer(), sa.ForeignKey("github_installations.installation_id"), nullable=False),
        sa.Column("default_branch", sa.String(255), nullable=False, server_default="main"),
    )
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "sandbox_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("e2b_sandbox_id", sa.String(128), nullable=True),
        sa.Column("repo", sa.String(255), nullable=False),
        sa.Column("ref", sa.String(255), nullable=False, server_default="main"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "symbols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("sandbox_runs.id"), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(128), nullable=False, unique=True),
        sa.Column("fcm_token", sa.Text(), nullable=False),
        sa.Column("label", sa.String(255), nullable=False, server_default=""),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "push_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    from alembic import op

    op.drop_table("push_events")
    op.drop_table("devices")
    op.drop_table("symbols")
    op.drop_table("sandbox_runs")
    op.drop_table("incidents")
    op.drop_table("repositories")
    op.drop_table("github_installations")
