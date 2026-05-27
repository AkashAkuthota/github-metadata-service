"""
Repository service layer.

Single responsibility: orchestrate the steps required to fulfil each
use case — validate inputs, call the GitHub client, call the repository
data layer, and return typed response schemas.

Rules enforced here:
  ✓ Calls the GitHub client for external data.
  ✓ Calls the repository repo for persistence.
  ✓ Raises domain exceptions from app.core.exceptions.
  ✓ Returns Pydantic response schemas — never raw ORM instances.

  ✗ No direct SQLAlchemy queries (those belong in repository_repo).
  ✗ No httpx imports or HTTP status codes (those belong in the client
    layer and the exception handlers respectively).
  ✗ No FastAPI-specific code.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidGitHubURLError,
    RepositoryAlreadyExistsError,
    RepositoryNotFoundError,
)
from app.core.logging import get_logger
from app.repositories.repository_repo import RepositoryRepository
from app.schemas.github import GitHubRepoSchema
from app.schemas.repository import (
    RepositoryCreateRequest,
    RepositoryListResponse,
    RepositoryResponse,
)
from app.services.github_client import GitHubClient

logger = get_logger(__name__)


class RepositoryService:
    """
    Orchestrates use cases for the Repository resource.

    Dependencies (GitHub client and repo layer) are injected via the
    constructor so they can be replaced with fakes in unit tests without
    patching module globals.
    """

    def __init__(
        self,
        github_client: GitHubClient,
        repo: RepositoryRepository,
    ) -> None:
        self._github = github_client
        self._repo = repo

    # ------------------------------------------------------------------
    # Public use-case methods
    # ------------------------------------------------------------------

    async def create_repository(
        self,
        session: AsyncSession,
        request: RepositoryCreateRequest,
    ) -> RepositoryResponse:
        """
        Fetch GitHub metadata for the submitted URL and persist it.

        Flow:
          1. Parse the validated URL into (owner, repo_name).
          2. Fetch metadata from GitHub — this gives us the stable github_id.
          3. Check the database for an existing record with that github_id.
          4. Raise RepositoryAlreadyExistsError if a duplicate is found.
          5. Persist the new record and return it.

        Note: GitHub is called before the duplicate check so that github_id
        (not the URL) is always the uniqueness anchor. A repository can be
        renamed or transferred; its github_id never changes.

        Raises:
            InvalidGitHubURLError:       URL does not resolve to owner/repo.
            GitHubNotFoundError:         GitHub returned 404 for the repo.
            GitHubRateLimitError:        GitHub rate limit exceeded.
            GitHubUpstreamError:         GitHub returned an error response.
            GitHubConnectivityError:     Could not reach GitHub.
            RepositoryAlreadyExistsError: github_id already in the database.
        """
        owner, repo_name = self._parse_github_url(request.github_url)

        logger.info("create_repository_start", owner=owner, repo_name=repo_name)

        # Step 1 — fetch from GitHub (raises domain exceptions on failure)
        github_data = await self._github.fetch_repository(owner, repo_name)

        # Step 2 — duplicate check using the stable github_id
        existing = await self._repo.get_by_github_id(session, github_data.github_id)
        if existing is not None:
            logger.info(
                "create_repository_conflict",
                github_id=github_data.github_id,
                existing_id=existing.id,
            )
            raise RepositoryAlreadyExistsError(
                github_id=github_data.github_id,
                existing_id=existing.id,
            )

        # Step 3 — persist
        repository = await self._repo.create(
            session,
            **self._map_github_data_to_fields(github_data),
        )

        # Commit so the new row is visible to subsequent requests.
        # The repo layer only flushes (gets DB-assigned id) — the service
        # layer owns the commit boundary.
        await session.commit()
        await session.refresh(repository)

        logger.info(
            "create_repository_success",
            id=repository.id,
            full_name=repository.full_name,
        )
        return RepositoryResponse.model_validate(repository)

    async def get_repository(
        self,
        session: AsyncSession,
        repository_id: int,
    ) -> RepositoryResponse:
        """
        Return a single repository by internal integer ID.

        Raises:
            RepositoryNotFoundError: No record with the given ID exists.
        """
        repository = await self._repo.get_by_id(session, repository_id)
        if repository is None:
            raise RepositoryNotFoundError(identifier=repository_id)
        return RepositoryResponse.model_validate(repository)

    async def refresh_repository(
        self,
        session: AsyncSession,
        repository_id: int,
    ) -> RepositoryResponse:
        """
        Re-fetch metadata from GitHub and update the stored record.

        This is the handler for PUT /repositories/{id}. It always calls
        GitHub — there is no staleness check. The caller decides when a
        refresh is warranted.

        Raises:
            RepositoryNotFoundError:  No local record with the given ID.
            GitHubNotFoundError:      Repo was deleted from GitHub since last fetch.
            GitHubRateLimitError:     GitHub rate limit exceeded.
            GitHubUpstreamError:      GitHub returned an error response.
            GitHubConnectivityError:  Could not reach GitHub.
        """
        repository = await self._repo.get_by_id(session, repository_id)
        if repository is None:
            raise RepositoryNotFoundError(identifier=repository_id)

        logger.info(
            "refresh_repository_start",
            id=repository_id,
            full_name=repository.full_name,
        )

        github_data = await self._github.fetch_repository(
            repository.owner,
            repository.repo_name,
        )

        updated = await self._repo.update(
            session,
            repository,
            description=github_data.description,
            html_url=github_data.html_url,
            stars=github_data.stars,
            forks=github_data.forks,
            language=github_data.language,
            github_updated_at=github_data.updated_at,
            last_fetched_at=datetime.now(UTC),
        )

        await session.commit()
        await session.refresh(updated)

        logger.info("refresh_repository_success", id=repository_id)
        return RepositoryResponse.model_validate(updated)

    async def delete_repository(
        self,
        session: AsyncSession,
        repository_id: int,
    ) -> None:
        """
        Delete a repository from the local store.

        Does not call GitHub — deletion is a local-only operation.

        Raises:
            RepositoryNotFoundError: No record with the given ID exists.
        """
        repository = await self._repo.get_by_id(session, repository_id)
        if repository is None:
            raise RepositoryNotFoundError(identifier=repository_id)

        await self._repo.delete(session, repository)
        await session.commit()
        logger.info("delete_repository_success", id=repository_id)

    async def list_repositories(
        self,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
    ) -> RepositoryListResponse:
        """
        Return a paginated list of all locally stored repositories.

        Does not call GitHub — returns only what is in the local database.
        """
        items, total = await self._repo.list_paginated(
            session,
            page=page,
            page_size=page_size,
        )
        return RepositoryListResponse(
            items=[RepositoryResponse.model_validate(r) for r in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_github_url(self, url: HttpUrl) -> tuple[str, str]:
        """
        Extract (owner, repo_name) from a validated GitHub URL.

        Pydantic has already confirmed the URL is on github.com with a
        two-segment path, so this is extraction, not re-validation.
        Strips a trailing `.git` suffix to handle clone URLs.

        Raises:
            InvalidGitHubURLError: Owner or repo name is empty after parsing.
        """
        path_parts = [p for p in (url.path or "").strip("/").split("/") if p]
        owner = path_parts[0]
        repo_name = path_parts[1].removesuffix(".git")

        if not owner or not repo_name:
            raise InvalidGitHubURLError(
                f"Could not extract owner and repository name from URL: {url}"
            )

        return owner, repo_name

    def _map_github_data_to_fields(self, data: GitHubRepoSchema) -> dict[str, Any]:
        """
        Translate a validated GitHub API schema into keyword arguments
        for RepositoryRepository.create().

        Centralising this mapping means any GitHub API field rename only
        needs to be updated in one place.
        """
        return {
            "github_id": data.github_id,
            "owner": data.owner.login,
            "repo_name": data.name,
            "full_name": data.full_name,
            "description": data.description,
            "html_url": data.html_url,
            "stars": data.stars,
            "forks": data.forks,
            "language": data.language,
            "github_created_at": data.created_at,
            "github_updated_at": data.updated_at,
            "last_fetched_at": datetime.now(UTC),
        }


# ------------------------------------------------------------------
# Module-level singleton wired to the real GitHub client and repo.
# Tests replace these dependencies by constructing RepositoryService
# with fakes — no monkeypatching required.
# ------------------------------------------------------------------
from app.repositories.repository_repo import repository_repo  # noqa: E402
from app.services.github_client import github_client  # noqa: E402

repository_service = RepositoryService(
    github_client=github_client,
    repo=repository_repo,
)
