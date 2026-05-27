"""
Repository ORM model.

Maps to the `repositories` table in PostgreSQL.
All timestamps are stored as TIMESTAMPTZ (timezone-aware) — never naive datetime.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Repository(Base):
    """
    Stores GitHub repository metadata fetched from the GitHub REST API.

    Primary key: integer auto-increment (`id`) — internal surrogate key.
    Uniqueness anchor: `github_id` (GitHub's own stable integer identifier).
      A repository can be renamed or transferred between owners; its
      github_id never changes. This makes it the correct uniqueness key.
    """

    __tablename__ = "repositories"

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Internal surrogate key, auto-assigned by PostgreSQL.",
    )

    # ------------------------------------------------------------------
    # GitHub identity fields
    # ------------------------------------------------------------------
    github_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="GitHub's own stable integer ID for this repository.",
    )
    owner: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Repository owner login (user or organisation).",
    )
    repo_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Repository name without the owner prefix.",
    )
    full_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Canonical {owner}/{repo_name} slug as returned by GitHub.",
    )
    html_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Browser-facing GitHub URL, e.g. https://github.com/tiangolo/fastapi",
    )

    # ------------------------------------------------------------------
    # Metadata fields (nullable — GitHub does not guarantee all are set)
    # ------------------------------------------------------------------
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Short description of the repository as set by the owner.",
    )
    language: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Primary programming language detected by GitHub.",
    )

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------
    stars: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Stargazers count at the time of last fetch.",
    )
    forks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Forks count at the time of last fetch.",
    )

    # ------------------------------------------------------------------
    # Timestamps — all TIMESTAMPTZ via SQLAlchemy's DateTime(timezone=True)
    # ------------------------------------------------------------------
    # GitHub timestamps: when the repo was created/last pushed to on GitHub.
    # These come directly from the API response and are stored as-is.
    github_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp when the GitHub repository was originally created.",
    )
    github_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp of the last push or metadata update on GitHub.",
    )

    # Service timestamps: managed by this service, not by GitHub.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Timestamp when this record was first inserted into our database.",
    )
    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Timestamp of the most recent successful GitHub API fetch for this record.",
    )

    # ------------------------------------------------------------------
    # Constraints and indexes
    # ------------------------------------------------------------------
    __table_args__ = (
        # DB-level uniqueness on github_id — the authoritative constraint.
        # Pydantic validation catches format errors early; this catches
        # concurrent inserts that pass validation simultaneously.
        UniqueConstraint("github_id", name="uq_repositories_github_id"),

        # Index on full_name supports the GET /repositories/by-name/{owner}/{repo}
        # endpoint without a sequential scan.
        Index("ix_repositories_full_name", "full_name"),

        # Composite index: filtering by owner is a common access pattern
        # (e.g. "show me all repos for this org"). Covers queries on owner
        # alone or owner+repo_name.
        Index("ix_repositories_owner_repo_name", "owner", "repo_name"),
    )

    def __repr__(self) -> str:
        return (
            f"<Repository id={self.id} full_name={self.full_name!r} "
            f"github_id={self.github_id} stars={self.stars}>"
        )
