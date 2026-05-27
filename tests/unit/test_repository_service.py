"""
Unit tests for RepositoryService.

Dependencies (GitHubClient, RepositoryRepository) are replaced with
AsyncMock objects so no database or network access occurs.

Tests verify:
  - Correct orchestration: GitHub is called, then DB is checked, then record created.
  - Duplicate detection raises RepositoryAlreadyExistsError.
  - Missing record raises RepositoryNotFoundError.
  - GitHub data is correctly mapped to DB fields.
  - Refresh delegates to the correct repo methods.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import RepositoryAlreadyExistsError, RepositoryNotFoundError
from app.models.repository import Repository
from app.schemas.github import GitHubOwner, GitHubRepoSchema
from app.schemas.repository import RepositoryCreateRequest
from app.services.repository_service import RepositoryService

# ---------------------------------------------------------------------------
# Helpers — build typed test objects without touching the DB
# ---------------------------------------------------------------------------

def make_github_schema(
    github_id: int = 116195547,
    owner: str = "tiangolo",
    name: str = "fastapi",
    stars: int = 75000,
    language: str | None = "Python",
) -> GitHubRepoSchema:
    return GitHubRepoSchema(
        id=github_id,
        name=name,
        full_name=f"{owner}/{name}",
        owner=GitHubOwner(login=owner),
        description="FastAPI framework",
        html_url=f"https://github.com/{owner}/{name}",
        stargazers_count=stars,
        forks_count=6100,
        language=language,
        created_at=datetime(2018, 12, 8, 8, 21, 47, tzinfo=UTC),
        updated_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
    )


def make_repository_orm(
    id: int = 1,
    github_id: int = 116195547,
    owner: str = "tiangolo",
    repo_name: str = "fastapi",
) -> Repository:
    """Build a Repository ORM instance with minimal required fields set."""
    repo = Repository()
    repo.id = id
    repo.github_id = github_id
    repo.owner = owner
    repo.repo_name = repo_name
    repo.full_name = f"{owner}/{repo_name}"
    repo.description = "FastAPI framework"
    repo.html_url = f"https://github.com/{owner}/{repo_name}"
    repo.stars = 75000
    repo.forks = 6100
    repo.language = "Python"
    repo.github_created_at = datetime(2018, 12, 8, 8, 21, 47, tzinfo=UTC)
    repo.github_updated_at = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    repo.created_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    repo.last_fetched_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    return repo


def make_service(
    github_response: GitHubRepoSchema | None = None,
    existing_repo: Repository | None = None,
    created_repo: Repository | None = None,
) -> tuple[RepositoryService, AsyncMock, AsyncMock]:
    """
    Build a RepositoryService with fully mocked dependencies.

    Returns (service, mock_github_client, mock_repo) so individual
    tests can assert on what was called and with what arguments.
    """
    mock_github = AsyncMock()
    mock_github.fetch_repository.return_value = (
        github_response or make_github_schema()
    )

    mock_repo = AsyncMock()
    mock_repo.get_by_github_id.return_value = existing_repo
    mock_repo.create.return_value = created_repo or make_repository_orm()
    mock_repo.get_by_id.return_value = existing_repo or make_repository_orm()
    mock_repo.update.return_value = created_repo or make_repository_orm()

    service = RepositoryService(github_client=mock_github, repo=mock_repo)
    return service, mock_github, mock_repo


# ---------------------------------------------------------------------------
# create_repository
# ---------------------------------------------------------------------------

class TestCreateRepository:
    async def test_calls_github_with_parsed_owner_and_repo(self):
        service, mock_github, _ = make_service()
        session = AsyncMock()

        await service.create_repository(
            session,
            RepositoryCreateRequest(github_url="https://github.com/tiangolo/fastapi"),  # type: ignore[arg-type]
        )

        mock_github.fetch_repository.assert_called_once_with("tiangolo", "fastapi")

    async def test_checks_db_for_duplicate_after_github_fetch(self):
        """GitHub is called first (to get github_id), then DB is checked."""
        github_schema = make_github_schema(github_id=999)
        service, mock_github, mock_repo = make_service(
            github_response=github_schema,
            existing_repo=None,
        )
        session = AsyncMock()

        await service.create_repository(
            session,
            RepositoryCreateRequest(github_url="https://github.com/tiangolo/fastapi"),  # type: ignore[arg-type]
        )

        # Duplicate check must use the github_id returned by the API
        mock_repo.get_by_github_id.assert_called_once_with(session, 999)

    async def test_raises_already_exists_when_github_id_in_db(self):
        existing = make_repository_orm(id=42, github_id=116195547)
        service, _, _ = make_service(existing_repo=existing)
        session = AsyncMock()

        with pytest.raises(RepositoryAlreadyExistsError) as exc_info:
            await service.create_repository(
                session,
                RepositoryCreateRequest(github_url="https://github.com/tiangolo/fastapi"),  # type: ignore[arg-type]
            )

        assert exc_info.value.existing_id == 42
        assert exc_info.value.github_id == 116195547

    async def test_creates_record_when_no_duplicate(self):
        service, _, mock_repo = make_service(existing_repo=None)
        session = AsyncMock()

        result = await service.create_repository(
            session,
            RepositoryCreateRequest(github_url="https://github.com/tiangolo/fastapi"),  # type: ignore[arg-type]
        )

        mock_repo.create.assert_called_once()
        assert result.id == 1

    async def test_maps_github_schema_fields_to_db_correctly(self):
        """Verify field mapping — especially the aliased fields (stars, forks)."""
        github_schema = make_github_schema(stars=99999, language="TypeScript")
        service, _, mock_repo = make_service(
            github_response=github_schema,
            existing_repo=None,
        )
        session = AsyncMock()

        await service.create_repository(
            session,
            RepositoryCreateRequest(github_url="https://github.com/tiangolo/fastapi"),  # type: ignore[arg-type]
        )

        _, kwargs = mock_repo.create.call_args
        assert kwargs["stars"] == 99999
        assert kwargs["language"] == "TypeScript"
        assert kwargs["github_id"] == 116195547
        assert kwargs["owner"] == "tiangolo"
        assert kwargs["repo_name"] == "fastapi"

    async def test_strips_git_suffix_from_url(self):
        service, mock_github, _ = make_service()
        session = AsyncMock()

        await service.create_repository(
            session,
            RepositoryCreateRequest(github_url="https://github.com/tiangolo/fastapi.git"),  # type: ignore[arg-type]
        )

        # .git suffix must be stripped before the GitHub API call
        mock_github.fetch_repository.assert_called_once_with("tiangolo", "fastapi")

    async def test_handles_null_language(self):
        """Repos without a detected language must not raise — language is nullable."""
        github_schema = make_github_schema(language=None)
        created = make_repository_orm()
        created.language = None
        service, _, mock_repo = make_service(
            github_response=github_schema,
            existing_repo=None,
            created_repo=created,
        )
        session = AsyncMock()

        result = await service.create_repository(
            session,
            RepositoryCreateRequest(github_url="https://github.com/tiangolo/fastapi"),  # type: ignore[arg-type]
        )

        assert result.language is None


# ---------------------------------------------------------------------------
# get_repository
# ---------------------------------------------------------------------------

class TestGetRepository:
    async def test_returns_response_when_found(self):
        orm_repo = make_repository_orm(id=5)
        service, _, mock_repo = make_service()
        mock_repo.get_by_id.return_value = orm_repo
        session = AsyncMock()

        result = await service.get_repository(session, 5)

        mock_repo.get_by_id.assert_called_once_with(session, 5)
        assert result.id == 5

    async def test_raises_not_found_when_missing(self):
        service, _, mock_repo = make_service()
        mock_repo.get_by_id.return_value = None
        session = AsyncMock()

        with pytest.raises(RepositoryNotFoundError) as exc_info:
            await service.get_repository(session, 999)

        assert "999" in str(exc_info.value)


# ---------------------------------------------------------------------------
# refresh_repository
# ---------------------------------------------------------------------------

class TestRefreshRepository:
    async def test_fetches_from_github_using_stored_owner_and_name(self):
        existing = make_repository_orm(owner="django", repo_name="django")
        service, mock_github, mock_repo = make_service()
        mock_repo.get_by_id.return_value = existing
        session = AsyncMock()

        await service.refresh_repository(session, 1)

        mock_github.fetch_repository.assert_called_once_with("django", "django")

    async def test_raises_not_found_when_local_record_missing(self):
        service, _, mock_repo = make_service()
        mock_repo.get_by_id.return_value = None
        session = AsyncMock()

        with pytest.raises(RepositoryNotFoundError):
            await service.refresh_repository(session, 42)

    async def test_calls_repo_update_with_refreshed_data(self):
        existing = make_repository_orm()
        updated_schema = make_github_schema(stars=99000)
        service, _, mock_repo = make_service(github_response=updated_schema)
        mock_repo.get_by_id.return_value = existing
        session = AsyncMock()

        await service.refresh_repository(session, 1)

        mock_repo.update.assert_called_once()
        _, kwargs = mock_repo.update.call_args
        assert kwargs["stars"] == 99000


# ---------------------------------------------------------------------------
# delete_repository
# ---------------------------------------------------------------------------

class TestDeleteRepository:
    async def test_calls_repo_delete_when_found(self):
        existing = make_repository_orm(id=3)
        service, _, mock_repo = make_service()
        mock_repo.get_by_id.return_value = existing
        session = AsyncMock()

        await service.delete_repository(session, 3)

        mock_repo.delete.assert_called_once_with(session, existing)

    async def test_raises_not_found_when_missing(self):
        service, _, mock_repo = make_service()
        mock_repo.get_by_id.return_value = None
        session = AsyncMock()

        with pytest.raises(RepositoryNotFoundError):
            await service.delete_repository(session, 999)
