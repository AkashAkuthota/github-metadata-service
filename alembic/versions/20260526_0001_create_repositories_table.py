"""create repositories table

Revision ID: 0001
Revises:
Create Date: 2026-05-26

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        # Primary key — integer auto-increment, PostgreSQL SERIAL equivalent
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),

        # GitHub identity
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("repo_name", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("html_url", sa.Text(), nullable=False),

        # Nullable metadata
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),

        # Counters
        sa.Column("stars", sa.Integer(), server_default="0", nullable=False),
        sa.Column("forks", sa.Integer(), server_default="0", nullable=False),

        # Timestamps — TIMESTAMPTZ (timezone=True) throughout
        sa.Column("github_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("github_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),

        # Table-level constraints
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_id", name="uq_repositories_github_id"),
    )

    # Indexes created separately for clarity and explicit naming
    op.create_index(
        "ix_repositories_full_name",
        "repositories",
        ["full_name"],
    )
    op.create_index(
        "ix_repositories_owner_repo_name",
        "repositories",
        ["owner", "repo_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_repositories_owner_repo_name", table_name="repositories")
    op.drop_index("ix_repositories_full_name", table_name="repositories")
    op.drop_table("repositories")
