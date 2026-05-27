"""
Repository data layer.

Single responsibility: translate between the service layer and the database.

Rules enforced here:
  ✓ All database access for the Repository model goes through this module.
  ✓ Methods accept and return SQLAlchemy ORM instances or primitives.
  ✓ No business logic — no validation, no external calls, no exception mapping.
  ✓ Callers (service layer) decide what to do with None returns.

Methods return None rather than raising when a record is not found —
the service layer raises RepositoryNotFoundError when appropriate.
That keeps this layer reusable: sometimes "not found" is an error,
sometimes it is expected (e.g. existence checks before inserts).
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository


class RepositoryRepository:
    """
    Data access object for the Repository model.

    Accepts an AsyncSession on every method call rather than storing it
    as instance state. This keeps the class stateless and makes it safe
    to use as a long-lived singleton — the session lifecycle is managed
    by the FastAPI dependency, not by this class.
    """

    async def create(
        self,
        session: AsyncSession,
        *,
        github_id: int,
        owner: str,
        repo_name: str,
        full_name: str,
        description: str | None,
        html_url: str,
        stars: int,
        forks: int,
        language: str | None,
        github_created_at: datetime,
        github_updated_at: datetime,
        last_fetched_at: datetime,
    ) -> Repository:
        """
        Insert a new repository record and return the persisted instance.

        Uses keyword-only arguments (after *) so callers cannot accidentally
        pass positional arguments in the wrong order for this many-field insert.
        """
        repository = Repository(
            github_id=github_id,
            owner=owner,
            repo_name=repo_name,
            full_name=full_name,
            description=description,
            html_url=html_url,
            stars=stars,
            forks=forks,
            language=language,
            github_created_at=github_created_at,
            github_updated_at=github_updated_at,
            last_fetched_at=last_fetched_at,
        )
        session.add(repository)
        # flush to get the DB-assigned id without committing the transaction.
        # The caller (service layer) is responsible for the final commit via
        # the session dependency in db/session.py.
        await session.flush()
        await session.refresh(repository)
        return repository

    async def get_by_id(
        self,
        session: AsyncSession,
        repository_id: int,
    ) -> Repository | None:
        """Return the repository with the given internal ID, or None."""
        result = await session.execute(
            select(Repository).where(Repository.id == repository_id)
        )
        return result.scalar_one_or_none()

    async def get_by_github_id(
        self,
        session: AsyncSession,
        github_id: int,
    ) -> Repository | None:
        """
        Return the repository matching GitHub's stable integer ID, or None.

        Used by the service layer before inserts to detect duplicates.
        github_id is indexed via the UNIQUE constraint, so this is an
        index seek rather than a sequential scan.
        """
        result = await session.execute(
            select(Repository).where(Repository.github_id == github_id)
        )
        return result.scalar_one_or_none()

    async def get_by_full_name(
        self,
        session: AsyncSession,
        owner: str,
        repo_name: str,
    ) -> Repository | None:
        """
        Return the repository matching owner + repo_name, or None.

        Used by GET /repositories/by-name/{owner}/{repo}.
        Covered by the composite index ix_repositories_owner_repo_name.
        """
        result = await session.execute(
            select(Repository).where(
                Repository.owner == owner,
                Repository.repo_name == repo_name,
            )
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        session: AsyncSession,
        repository: Repository,
        *,
        description: str | None,
        html_url: str,
        stars: int,
        forks: int,
        language: str | None,
        github_updated_at: datetime,
        last_fetched_at: datetime,
    ) -> Repository:
        """
        Update mutable metadata fields on an existing repository record.

        Accepts the ORM instance directly — the caller is responsible for
        fetching it first. Only the fields that GitHub can change between
        fetches are updated; identity fields (github_id, owner, full_name)
        are left unchanged.

        GitHub *can* rename repos and transfer ownership, which would change
        owner and full_name. Supporting that case is out of scope here — a
        separate reconciliation job would handle it in production.
        """
        repository.description = description
        repository.html_url = html_url
        repository.stars = stars
        repository.forks = forks
        repository.language = language
        repository.github_updated_at = github_updated_at
        repository.last_fetched_at = last_fetched_at

        session.add(repository)
        await session.flush()
        await session.refresh(repository)
        return repository

    async def delete(
        self,
        session: AsyncSession,
        repository: Repository,
    ) -> None:
        """
        Delete a repository record from the database.

        The caller is responsible for fetching the record and verifying
        it exists before calling this method.
        """
        await session.delete(repository)
        await session.flush()

    async def list_paginated(
        self,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Repository], int]:
        """
        Return a page of repositories and the total count.

        Returns a tuple of (items, total) so the service layer can build
        the paginated response envelope without a second call.

        Ordered by id descending — most recently added first.
        Two queries are issued: one for the count, one for the page.
        This is intentionally explicit rather than using a subquery so the
        query plan is easy to understand and the EXPLAIN output is readable.
        """
        count_result = await session.execute(
            select(func.count()).select_from(Repository)
        )
        total: int = count_result.scalar_one()

        items_result = await session.execute(
            select(Repository)
            .order_by(Repository.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(items_result.scalars().all())

        return items, total


# Module-level singleton — stateless, safe to share across requests.
repository_repo = RepositoryRepository()
