"""
Unit tests for GitHubClient exception translation.

Uses respx as a context manager (not a class method decorator) to intercept
httpx requests at the transport level. No real network calls are made.

Note on respx usage:
  @respx.mock as a class method decorator conflicts with pytest's fixture
  injection — both try to control positional argument order on the same
  method, causing argument mismatches. Using 'with respx.mock(...) as mock:'
  inside each test is unambiguous and works correctly with pytest fixtures.

Covers:
  - Successful response → GitHubRepoSchema with correct field mapping
  - 404 response → GitHubNotFoundError
  - 429 response → GitHubRateLimitError (with and without Retry-After)
  - 403 with rate-limit body → GitHubRateLimitError
  - 500 response → GitHubUpstreamError (502 territory)
  - TimeoutException → GitHubConnectivityError (503 territory)
  - ConnectError → GitHubConnectivityError (503 territory)
"""

import httpx
import pytest
import respx

from app.core.exceptions import (
    GitHubConnectivityError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubUpstreamError,
)
from app.services.github_client import GitHubClient

GITHUB_BASE = "https://api.github.com"

# Minimal valid GitHub API response — contains every field our schema declares
VALID_GITHUB_RESPONSE = {
    "id": 116195547,
    "name": "fastapi",
    "full_name": "tiangolo/fastapi",
    "owner": {"login": "tiangolo"},
    "description": "FastAPI framework",
    "html_url": "https://github.com/tiangolo/fastapi",
    "stargazers_count": 75000,
    "forks_count": 6100,
    "language": "Python",
    "created_at": "2018-12-08T08:21:47Z",
    "updated_at": "2024-01-15T10:00:00Z",
    # Extra field — our schema must ignore it without raising
    "private": False,
}


@pytest.fixture
def github_client() -> GitHubClient:
    """Return a GitHubClient pointing at the real GitHub base URL."""
    return GitHubClient(token=None, timeout=5.0)


# ---------------------------------------------------------------------------
# Successful fetch
# ---------------------------------------------------------------------------

class TestSuccessfulFetch:
    async def test_returns_typed_schema(self, github_client):
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/tiangolo/fastapi").mock(
                return_value=httpx.Response(200, json=VALID_GITHUB_RESPONSE)
            )

            result = await github_client.fetch_repository("tiangolo", "fastapi")

        assert result.github_id == 116195547
        assert result.owner.login == "tiangolo"
        assert result.name == "fastapi"
        assert result.stars == 75000   # aliased from stargazers_count
        assert result.forks == 6100    # aliased from forks_count
        assert result.language == "Python"

    async def test_extra_fields_are_silently_ignored(self, github_client):
        """GitHub returns 100+ fields; unknown ones must not cause ValidationError."""
        response_with_extras = {
            **VALID_GITHUB_RESPONSE,
            "has_wiki": True,
            "has_projects": False,
            "subscribers_count": 3000,
            "network_count": 6000,
        }
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/tiangolo/fastapi").mock(
                return_value=httpx.Response(200, json=response_with_extras)
            )

            result = await github_client.fetch_repository("tiangolo", "fastapi")

        assert result.github_id == 116195547

    async def test_null_language_is_handled(self, github_client):
        response = {**VALID_GITHUB_RESPONSE, "language": None}
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/tiangolo/fastapi").mock(
                return_value=httpx.Response(200, json=response)
            )

            result = await github_client.fetch_repository("tiangolo", "fastapi")

        assert result.language is None


# ---------------------------------------------------------------------------
# 404 — repository not found on GitHub
# ---------------------------------------------------------------------------

class TestNotFoundError:
    async def test_404_raises_github_not_found_error(self, github_client):
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/nobody/doesnotexist").mock(
                return_value=httpx.Response(404, json={"message": "Not Found"})
            )

            with pytest.raises(GitHubNotFoundError) as exc_info:
                await github_client.fetch_repository("nobody", "doesnotexist")

        assert exc_info.value.owner == "nobody"
        assert exc_info.value.repo == "doesnotexist"


# ---------------------------------------------------------------------------
# Rate limiting — 429 and rate-limit 403
# ---------------------------------------------------------------------------

class TestRateLimitError:
    async def test_429_raises_rate_limit_error(self, github_client):
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/tiangolo/fastapi").mock(
                return_value=httpx.Response(
                    429,
                    headers={"Retry-After": "60"},
                    json={"message": "rate limit exceeded"},
                )
            )

            with pytest.raises(GitHubRateLimitError) as exc_info:
                await github_client.fetch_repository("tiangolo", "fastapi")

        assert exc_info.value.retry_after == 60

    async def test_429_without_retry_after_header(self, github_client):
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/tiangolo/fastapi").mock(
                return_value=httpx.Response(
                    429, json={"message": "rate limit exceeded"}
                )
            )

            with pytest.raises(GitHubRateLimitError) as exc_info:
                await github_client.fetch_repository("tiangolo", "fastapi")

        assert exc_info.value.retry_after is None

    async def test_403_with_rate_limit_message_raises_rate_limit_error(
        self, github_client
    ):
        """GitHub sometimes signals rate limiting via 403 with a specific message."""
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/tiangolo/fastapi").mock(
                return_value=httpx.Response(
                    403,
                    json={"message": "API rate limit exceeded for ..."},
                )
            )

            with pytest.raises(GitHubRateLimitError):
                await github_client.fetch_repository("tiangolo", "fastapi")


# ---------------------------------------------------------------------------
# Upstream errors — GitHub responded with a non-success status (→ 502)
# ---------------------------------------------------------------------------

class TestUpstreamError:
    async def test_500_raises_upstream_error(self, github_client):
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/tiangolo/fastapi").mock(
                return_value=httpx.Response(
                    500, json={"message": "Internal Server Error"}
                )
            )

            with pytest.raises(GitHubUpstreamError) as exc_info:
                await github_client.fetch_repository("tiangolo", "fastapi")

        assert exc_info.value.status_code == 500

    async def test_503_from_github_raises_upstream_error(self, github_client):
        """GitHub returning 503 is an error on their side — still maps to 502 for us."""
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/tiangolo/fastapi").mock(
                return_value=httpx.Response(
                    503, json={"message": "Service Unavailable"}
                )
            )

            with pytest.raises(GitHubUpstreamError) as exc_info:
                await github_client.fetch_repository("tiangolo", "fastapi")

        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# Connectivity errors — no response received at all (→ 503)
# ---------------------------------------------------------------------------

class TestConnectivityError:
    async def test_timeout_raises_connectivity_error(self, github_client):
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/tiangolo/fastapi").mock(
                side_effect=httpx.TimeoutException("timed out")
            )

            with pytest.raises(GitHubConnectivityError) as exc_info:
                await github_client.fetch_repository("tiangolo", "fastapi")

        assert (
            "timed out" in exc_info.value.message.lower()
            or "timeout" in exc_info.value.message.lower()
        )

    async def test_connect_error_raises_connectivity_error(self, github_client):
        with respx.mock(base_url=GITHUB_BASE, assert_all_called=False) as mock:
            mock.get("/repos/tiangolo/fastapi").mock(
                side_effect=httpx.ConnectError("connection refused")
            )

            with pytest.raises(GitHubConnectivityError):
                await github_client.fetch_repository("tiangolo", "fastapi")
