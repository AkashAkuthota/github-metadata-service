"""
Repository API route handlers — v1.

Each handler has exactly three responsibilities:
  1. Declare the request shape (path params, query params, request body).
  2. Call one service method.
  3. Return a typed response with the correct status code.

No business logic. No exception handling. No database access.
All of that lives in the service layer and exception handlers respectively.
"""

from fastapi import APIRouter, Query, status

from app.api.dependencies import DBSession, RepoService
from app.schemas.repository import (
    RepositoryCreateRequest,
    RepositoryListResponse,
    RepositoryResponse,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a GitHub repository URL to fetch and store its metadata.",
    responses={
        409: {"description": "Repository already exists in the local store."},
        404: {"description": "Repository not found on GitHub."},
        422: {"description": "Invalid GitHub URL format."},
        429: {"description": "GitHub API rate limit exceeded."},
        502: {"description": "GitHub API returned an error response."},
        503: {"description": "GitHub API is unreachable."},
    },
)
async def create_repository(
    request: RepositoryCreateRequest,
    session: DBSession,
    service: RepoService,
) -> RepositoryResponse:
    return await service.create_repository(session, request)


@router.get(
    "",
    response_model=RepositoryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all locally stored repositories with pagination.",
)
async def list_repositories(
    session: DBSession,
    service: RepoService,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
) -> RepositoryListResponse:
    return await service.list_repositories(session, page=page, page_size=page_size)


@router.get(
    "/{repository_id}",
    response_model=RepositoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a stored repository by its internal integer ID.",
    responses={
        404: {"description": "Repository not found in the local store."},
    },
)
async def get_repository(
    repository_id: int,
    session: DBSession,
    service: RepoService,
) -> RepositoryResponse:
    return await service.get_repository(session, repository_id)


@router.put(
    "/{repository_id}",
    response_model=RepositoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Re-fetch metadata from GitHub and update the stored record.",
    responses={
        404: {"description": "Repository not found in the local store."},
        502: {"description": "GitHub API returned an error response."},
        503: {"description": "GitHub API is unreachable."},
    },
)
async def refresh_repository(
    repository_id: int,
    session: DBSession,
    service: RepoService,
) -> RepositoryResponse:
    return await service.refresh_repository(session, repository_id)


@router.delete(
    "/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a repository from the local store.",
    responses={
        404: {"description": "Repository not found in the local store."},
    },
)
async def delete_repository(
    repository_id: int,
    session: DBSession,
    service: RepoService,
) -> None:
    await service.delete_repository(session, repository_id)
