"""
Domain exception hierarchy.

Rules:
- All exceptions are pure Python — zero HTTP/FastAPI coupling.
- Route exception handlers (app/api/exception_handlers.py) are the ONLY
  place that maps these to HTTP status codes.
- Service and repository layers raise these; they never raise HTTPException.
"""


class AppBaseException(Exception):
    """Base class for all application domain exceptions."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# URL / Input validation
# ---------------------------------------------------------------------------


class InvalidGitHubURLError(AppBaseException):
    """
    Raised when the submitted URL is not a valid GitHub repository URL.

    Covers:
    - Wrong host (not github.com)
    - Path does not resolve to /{owner}/{repo}
    - Owner or repo name contains invalid characters
    """


# ---------------------------------------------------------------------------
# Local data layer
# ---------------------------------------------------------------------------


class RepositoryNotFoundError(AppBaseException):
    """Raised when a repository cannot be located in the local database."""

    def __init__(self, identifier: str | int) -> None:
        self.identifier = identifier
        super().__init__(f"Repository not found: {identifier!r}")


class RepositoryAlreadyExistsError(AppBaseException):
    """
    Raised when a POST attempts to create a repository that already exists
    in the local database (conflict on github_id).

    Carries the existing record's local ID so the handler can include it
    in the 409 response body.
    """

    def __init__(self, github_id: int, existing_id: int) -> None:
        self.github_id = github_id
        self.existing_id = existing_id
        super().__init__(
            f"Repository with github_id={github_id} already exists (id={existing_id})"
        )


# ---------------------------------------------------------------------------
# GitHub API errors — split by failure mode
# ---------------------------------------------------------------------------


class GitHubAPIError(AppBaseException):
    """Base class for all GitHub API interaction failures."""


class GitHubNotFoundError(GitHubAPIError):
    """
    GitHub returned HTTP 404 for the requested repository.
    Maps to 404 Not Found on our API.
    """

    def __init__(self, owner: str, repo: str) -> None:
        self.owner = owner
        self.repo = repo
        super().__init__(f"GitHub repository not found: {owner}/{repo}")


class GitHubRateLimitError(GitHubAPIError):
    """
    GitHub returned HTTP 429 or a 403 with a rate-limit header.

    Carries retry_after (seconds) when provided by GitHub so the
    exception handler can forward it as a Retry-After header.
    Maps to 429 Too Many Requests on our API.
    """

    def __init__(self, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        msg = "GitHub API rate limit exceeded"
        if retry_after is not None:
            msg += f"; retry after {retry_after}s"
        super().__init__(msg)


class GitHubUpstreamError(GitHubAPIError):
    """
    GitHub returned an error HTTP response (e.g. 5xx).

    The upstream responded but with a non-success status.
    Maps to 502 Bad Gateway on our API.
    """

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"GitHub API returned error response: HTTP {status_code}"
            + (f" — {detail}" if detail else "")
        )


class GitHubConnectivityError(GitHubAPIError):
    """
    Could not establish a connection to GitHub (timeout, DNS failure,
    network unreachable, etc.).

    Distinct from GitHubUpstreamError: here we never received any response.
    Maps to 503 Service Unavailable on our API.
    """

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(
            "GitHub API is unreachable"
            + (f": {detail}" if detail else "")
        )
