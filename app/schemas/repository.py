"""
Pydantic v2 schemas for the Repository API resource.

Three distinct schema types, each with a single responsibility:

  RepositoryCreateRequest  — what the client sends to POST /repositories
  RepositoryResponse       — what our API returns for any repository resource
  RepositoryListResponse   — paginated wrapper for GET /repositories

These schemas are the public API contract. They are deliberately decoupled
from both the ORM model (app/models/repository.py) and the GitHub API schema
(app/schemas/github.py) so each can evolve independently.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class RepositoryCreateRequest(BaseModel):
    """
    Request body for POST /repositories.

    Accepts a GitHub repository URL and nothing else. All other metadata
    is fetched from GitHub — clients should not submit it directly.
    """

    github_url: HttpUrl = Field(
        ...,
        description=(
            "Full URL of a public GitHub repository. "
            "Example: https://github.com/tiangolo/fastapi"
        ),
        examples=["https://github.com/tiangolo/fastapi"],
    )

    @field_validator("github_url")
    @classmethod
    def must_be_github_repo_url(cls, v: HttpUrl) -> HttpUrl:
        """
        Tier-1 validation: structural check at the Pydantic boundary.

        Confirms the URL is on github.com and has a two-segment path
        (owner/repo). Deep domain validation (e.g. checking for invalid
        characters in the owner name) is handled in the service layer,
        which raises typed domain exceptions that map to clean HTTP errors.
        """
        host = v.host or ""
        if host not in ("github.com", "www.github.com"):
            raise ValueError("URL must point to github.com")

        # Strip leading slash, split path segments
        path_parts = [p for p in (v.path or "").strip("/").split("/") if p]
        if len(path_parts) != 2:  # noqa: PLR2004
            raise ValueError(
                "URL must point to a repository: https://github.com/{owner}/{repo}"
            )

        return v


class RepositoryResponse(BaseModel):
    """
    API response schema for a single repository resource.

    Returned by:
      POST   /repositories         (201 Created)
      GET    /repositories/{id}    (200 OK)
      PUT    /repositories/{id}    (200 OK)

    Field names follow our API contract, not GitHub's naming conventions.
    Clients should treat this as stable; the ORM model or GitHub response
    shape can change without affecting this contract.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    github_id: int
    owner: str
    repo_name: str
    full_name: str
    description: str | None
    html_url: str
    stars: int
    forks: int
    language: str | None
    github_created_at: datetime
    github_updated_at: datetime
    created_at: datetime
    last_fetched_at: datetime


class RepositoryListResponse(BaseModel):
    """
    Paginated response for GET /repositories.

    Keeps the pagination envelope consistent so clients can rely on
    `items`, `total`, `page`, and `page_size` being present on every
    list response — even if pagination is not yet needed, establishing
    this envelope now avoids a breaking API change later.
    """

    items: list[RepositoryResponse]
    total: int = Field(..., description="Total number of repositories in the store.")
    page: int = Field(..., ge=1, description="Current page number (1-indexed).")
    page_size: int = Field(..., ge=1, le=100, description="Number of items per page.")
