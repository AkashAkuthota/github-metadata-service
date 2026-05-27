"""
Pydantic v2 schema for the GitHub REST API repository response.

This schema models exactly what GitHub sends back for:
  GET /repos/{owner}/{repo}

Purpose:
- Parse and validate the raw JSON from GitHub at the boundary.
- Alias camelCase / non-obvious GitHub field names to our naming conventions.
- Declare which fields are nullable so callers never have to guess.

This schema is an internal contract between the GitHub client and the
service layer. It is never serialised to API clients — use RepositoryResponse
for that.

Reference: https://docs.github.com/en/rest/repos/repos#get-a-repository
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GitHubOwner(BaseModel):
    """Nested owner object returned by the GitHub API."""

    model_config = ConfigDict(populate_by_name=True)

    login: str = Field(..., description="Owner's GitHub username or organisation login.")


class GitHubRepoSchema(BaseModel):
    """
    Validated representation of a GitHub repository API response.

    Only the fields we actually store are declared here. Pydantic v2
    ignores extra fields by default when extra="ignore", so the full
    GitHub response (which has 100+ fields) is accepted without error.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        # GitHub returns many more fields than we need — ignore the rest
        # rather than raising a validation error.
        extra="ignore",
    )

    # GitHub's own stable integer ID — our uniqueness anchor.
    # Never changes even if the repo is renamed or transferred.
    github_id: int = Field(..., alias="id")

    # Nested owner object — we extract only the login string.
    owner: GitHubOwner

    # Repository name without the owner prefix (e.g. "fastapi")
    name: str

    # Canonical "{owner}/{name}" slug (e.g. "tiangolo/fastapi")
    full_name: str

    # Optional prose description set by the repo owner
    description: str | None = None

    # Browser-facing URL
    html_url: str

    # Stargazers count — GitHub's field name is verbose
    stars: int = Field(..., alias="stargazers_count")

    # Forks count
    forks: int = Field(..., alias="forks_count")

    # Primary detected language — null when GitHub can't determine it
    # (e.g. documentation-only repos)
    language: str | None = None

    # ISO 8601 timestamps — Pydantic parses these into timezone-aware datetimes
    created_at: datetime
    updated_at: datetime
