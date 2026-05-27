"""
GitHub REST API client.

Responsibilities (and hard boundaries):
  ✓ Make HTTP requests to the GitHub API
  ✓ Authenticate requests with a token when configured
  ✓ Enforce timeouts on every request
  ✓ Parse and validate the raw response into a typed schema
  ✓ Translate HTTP / network errors into domain exceptions

  ✗ No business logic (that belongs in the service layer)
  ✗ No database access
  ✗ No knowledge of FastAPI or HTTP status codes

The client is designed to be used as a long-lived singleton (one
httpx.AsyncClient per application lifetime) so that the underlying
TCP connection pool is reused across requests. The lifespan in main.py
is responsible for opening and closing it.
"""

import httpx

from app.core.config import settings
from app.core.exceptions import (
    GitHubConnectivityError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubUpstreamError,
)
from app.core.logging import get_logger
from app.schemas.github import GitHubRepoSchema

logger = get_logger(__name__)


class GitHubClient:
    """
    Async wrapper around the GitHub REST API.

    Instantiate once at application startup and inject via FastAPI
    dependency. All methods are coroutines and must be awaited.

    Args:
        token: Optional GitHub personal access token.
               Unauthenticated: 60 req/hr.
               Authenticated:   5,000 req/hr.
        timeout: Per-request timeout in seconds. Applies to both
                 connect and read phases individually.
        base_url: GitHub API base URL. Overridable for testing.
    """

    def __init__(
        self,
        token: str | None = None,
        timeout: float = settings.github_request_timeout,
        base_url: str = str(settings.github_api_base_url),
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # httpx.Timeout splits timeout into connect, read, write, pool phases.
        # Using a single float sets the same value for all phases, which is
        # the safest default — prevents slow-connect AND slow-read hangs.
        self._timeout = httpx.Timeout(timeout)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=self._timeout,
            # Follow redirects — GitHub occasionally redirects renamed repos
            follow_redirects=True,
        )

    async def fetch_repository(self, owner: str, repo: str) -> GitHubRepoSchema:
        """
        Fetch metadata for a single repository from the GitHub API.

        Args:
            owner: Repository owner login (user or organisation).
            repo:  Repository name.

        Returns:
            GitHubRepoSchema — validated, typed representation of the
            GitHub API response.

        Raises:
            GitHubNotFoundError:     GitHub returned 404.
            GitHubRateLimitError:    GitHub returned 429 or rate-limit 403.
            GitHubUpstreamError:     GitHub returned any other error response.
            GitHubConnectivityError: Request timed out or network failure.
        """
        url = f"/repos/{owner}/{repo}"
        logger.info("github_api_request", method="GET", url=url)

        try:
            response = await self._client.get(url)
        except httpx.TimeoutException as exc:
            # Request never completed — GitHub was unreachable within the
            # configured timeout. Maps to 503 Service Unavailable.
            logger.warning(
                "github_api_timeout",
                url=url,
                timeout=self._timeout.read,
                error=str(exc),
            )
            raise GitHubConnectivityError(
                f"Request to GitHub timed out after {settings.github_request_timeout}s"
            ) from exc
        except httpx.ConnectError as exc:
            # DNS failure, connection refused, or network unreachable.
            # Also maps to 503 — we never received any response.
            logger.warning("github_api_connect_error", url=url, error=str(exc))
            raise GitHubConnectivityError(
                f"Could not connect to GitHub API: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            # Catch-all for any other httpx transport-level error
            # (e.g. SSL failure, proxy error). Still 503 — no response received.
            logger.warning("github_api_request_error", url=url, error=str(exc))
            raise GitHubConnectivityError(
                f"GitHub API request failed: {exc}"
            ) from exc

        # --- We received an HTTP response; now inspect the status code ---

        logger.info(
            "github_api_response",
            url=url,
            status_code=response.status_code,
        )

        if response.status_code == 404:
            raise GitHubNotFoundError(owner=owner, repo=repo)

        if response.status_code == 429 or (
            response.status_code == 403
            and "rate limit" in response.text.lower()
        ):
            # GitHub signals rate limiting via 429, or occasionally via
            # 403 with a rate-limit message. Extract Retry-After if present.
            retry_after_raw = response.headers.get("Retry-After") or response.headers.get(
                "X-RateLimit-Reset"
            )
            retry_after: int | None = None
            if retry_after_raw and retry_after_raw.isdigit():
                retry_after = int(retry_after_raw)

            logger.warning(
                "github_rate_limit_hit",
                retry_after=retry_after,
                status_code=response.status_code,
            )
            raise GitHubRateLimitError(retry_after=retry_after)

        if not response.is_success:
            # Any other non-2xx response — GitHub responded but with an error.
            # Maps to 502 Bad Gateway: upstream answered, but negatively.
            logger.error(
                "github_api_upstream_error",
                status_code=response.status_code,
                response_body=response.text[:500],  # truncate for log safety
            )
            raise GitHubUpstreamError(
                status_code=response.status_code,
                detail=response.text[:200],
            )

        # --- Success path: parse and validate the response body ---
        return GitHubRepoSchema.model_validate(response.json())

    async def close(self) -> None:
        """Close the underlying httpx client and release connections."""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Module-level singleton — initialised at application startup via lifespan.
# Injected into FastAPI dependencies rather than instantiated per-request.
# ---------------------------------------------------------------------------
github_client = GitHubClient(token=settings.github_token)
