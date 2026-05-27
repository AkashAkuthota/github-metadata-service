"""
Centralized exception-to-HTTP mapping.

This is the ONLY place in the codebase that imports both domain exceptions
and HTTP status codes together. Every other layer raises or catches domain
exceptions only.

Design:
- Each handler receives a domain exception and returns a JSONResponse.
- The error envelope is consistent across all error responses:
    { "error": "<machine_readable_code>", "message": "<human_readable>" }
- Handlers are registered on the FastAPI app in main.py via
  register_exception_handlers(app).

Status code mapping:
  InvalidGitHubURLError          → 422 Unprocessable Entity
  RepositoryNotFoundError        → 404 Not Found
  RepositoryAlreadyExistsError   → 409 Conflict
  GitHubNotFoundError            → 404 Not Found
  GitHubRateLimitError           → 429 Too Many Requests
  GitHubUpstreamError            → 502 Bad Gateway
  GitHubConnectivityError        → 503 Service Unavailable
  RequestValidationError         → 422 (override FastAPI default envelope)
  Exception (catch-all)          → 500 Internal Server Error
"""

import traceback

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    GitHubConnectivityError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubUpstreamError,
    InvalidGitHubURLError,
    RepositoryAlreadyExistsError,
    RepositoryNotFoundError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def _error_response(
    status_code: int,
    error: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a consistent JSON error envelope."""
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "message": message},
        headers=headers,
    )


# ------------------------------------------------------------------
# Handler functions
# ------------------------------------------------------------------

async def handle_invalid_github_url(
    request: Request,
    exc: InvalidGitHubURLError,
) -> JSONResponse:
    return _error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        error="invalid_github_url",
        message=exc.message,
    )


async def handle_repository_not_found(
    request: Request,
    exc: RepositoryNotFoundError,
) -> JSONResponse:
    return _error_response(
        status.HTTP_404_NOT_FOUND,
        error="repository_not_found",
        message=exc.message,
    )


async def handle_repository_already_exists(
    request: Request,
    exc: RepositoryAlreadyExistsError,
) -> JSONResponse:
    # Include the existing record's ID so the client can GET it immediately
    # without a second lookup — avoids an unnecessary round trip.
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": "repository_already_exists",
            "message": exc.message,
            "existing_id": exc.existing_id,
        },
    )


async def handle_github_not_found(
    request: Request,
    exc: GitHubNotFoundError,
) -> JSONResponse:
    return _error_response(
        status.HTTP_404_NOT_FOUND,
        error="github_repository_not_found",
        message=exc.message,
    )


async def handle_github_rate_limit(
    request: Request,
    exc: GitHubRateLimitError,
) -> JSONResponse:
    # Forward Retry-After when GitHub provided it so well-behaved clients
    # can back off for the correct duration without guessing.
    headers: dict[str, str] = {}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)

    return _error_response(
        status.HTTP_429_TOO_MANY_REQUESTS,
        error="github_rate_limit_exceeded",
        message=exc.message,
        headers=headers or None,
    )


async def handle_github_upstream_error(
    request: Request,
    exc: GitHubUpstreamError,
) -> JSONResponse:
    # 502: GitHub responded, but with an error.
    # Distinct from 503 where we couldn't reach GitHub at all.
    return _error_response(
        status.HTTP_502_BAD_GATEWAY,
        error="github_upstream_error",
        message=exc.message,
    )


async def handle_github_connectivity_error(
    request: Request,
    exc: GitHubConnectivityError,
) -> JSONResponse:
    # 503: Could not reach GitHub — timeout, DNS failure, network unreachable.
    return _error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        error="github_service_unavailable",
        message=exc.message,
    )


async def handle_request_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # Pydantic v2 stores the original exception object in error["ctx"]["error"],
    # which is a ValueError (or subclass). JSONResponse cannot serialize raw
    # exception objects, so we stringify every value in the ctx dict before
    # handing the errors list to the JSON encoder.
    cleaned_errors = []
    for error in exc.errors():
        error_copy = error.copy()
        if "ctx" in error_copy:
            error_copy["ctx"] = {
                key: str(value)
                for key, value in error_copy["ctx"].items()
            }
        cleaned_errors.append(error_copy)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": "Request validation failed.",
            "detail": cleaned_errors,
        },
    )


async def handle_unhandled_exception(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    # Log the full traceback for ops visibility, but return only a
    # generic message to the client — never leak internal details.
    logger.error(
        "unhandled_exception",
        method=request.method,
        url=str(request.url),
        exc_type=type(exc).__name__,
        traceback=traceback.format_exc(),
    )
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        error="internal_server_error",
        message="An unexpected error occurred. Please try again later.",
    )


# ------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------

def register_exception_handlers(app: FastAPI) -> None:
    """
    Attach all exception handlers to the FastAPI application.

    Call this once in the app factory (main.py) after creating the app.
    More specific exception types must be registered before their base
    classes so FastAPI's handler lookup finds the right one.
    """
    # Domain exceptions — ordered from most specific to most general
    app.add_exception_handler(InvalidGitHubURLError, handle_invalid_github_url)          # type: ignore[arg-type]
    app.add_exception_handler(RepositoryNotFoundError, handle_repository_not_found)      # type: ignore[arg-type]
    app.add_exception_handler(RepositoryAlreadyExistsError, handle_repository_already_exists)  # type: ignore[arg-type]
    app.add_exception_handler(GitHubNotFoundError, handle_github_not_found)              # type: ignore[arg-type]
    app.add_exception_handler(GitHubRateLimitError, handle_github_rate_limit)            # type: ignore[arg-type]
    app.add_exception_handler(GitHubUpstreamError, handle_github_upstream_error)         # type: ignore[arg-type]
    app.add_exception_handler(GitHubConnectivityError, handle_github_connectivity_error) # type: ignore[arg-type]

    # FastAPI / Pydantic validation errors — override the default envelope
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)   # type: ignore[arg-type]

    # Catch-all — must be last
    app.add_exception_handler(Exception, handle_unhandled_exception)
