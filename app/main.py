"""
FastAPI application factory.

Uses the factory pattern (create_app) rather than a module-level `app`
singleton so that tests can create isolated app instances with overridden
dependencies without affecting each other.

Lifespan manages startup and shutdown:
  - Startup:  configure logging, verify DB connectivity.
  - Shutdown: close the GitHub HTTP client, dispose the DB engine pool.

The module-level `app` instance is what uvicorn runs in production.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.exception_handlers import register_exception_handlers
from app.api.v1.repositories import router as repositories_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import engine
from app.services.github_client import github_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application startup and shutdown.

    FastAPI's lifespan replaces the deprecated @app.on_event("startup")
    pattern and guarantees the shutdown block runs even if startup fails
    partway through.
    """
    configure_logging()
    logger = get_logger(__name__)
    logger.info(
        "application_startup",
        app_name=settings.app_name,
        app_env=settings.app_env,
        debug=settings.debug,
    )

    yield  # Application is running — handle requests here

    # --- Shutdown ---
    logger.info("application_shutdown", app_name=settings.app_name)
    await github_client.close()
    await engine.dispose()


def create_app() -> FastAPI:
    """
    Construct and configure the FastAPI application.

    Separating construction into a factory function keeps main.py
    import-time side effects minimal and allows tests to call
    create_app() independently.
    """
    app = FastAPI(
        title="GitHub Metadata Service",
        description=(
            "Async REST API for fetching and storing GitHub repository metadata. "
            "Submitting a GitHub URL triggers a live fetch from the GitHub API; "
            "results are persisted in PostgreSQL and available via CRUD endpoints."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Routers
    app.include_router(repositories_router, prefix="/api/v1")

    # Exception handlers — registered after routers so FastAPI's own
    # validation handlers are already in place before we override them.
    register_exception_handlers(app)

    return app


# ------------------------------------------------------------------
# Health endpoints — registered directly on the factory output so they
# are not versioned (health checks must be stable across API versions).
# ------------------------------------------------------------------

app = create_app()


@app.get(
    "/health",
    tags=["health"],
    summary="Liveness check — confirms the process is running.",
    response_class=JSONResponse,
)
async def health_liveness() -> dict[str, str]:
    """Returns 200 immediately. No DB or external service checks."""
    return {"status": "ok"}


@app.get(
    "/health/ready",
    tags=["health"],
    summary="Readiness check — confirms DB connectivity.",
    response_class=JSONResponse,
)
async def health_readiness() -> dict[str, str]:
    """
    Attempts a cheap DB query (SELECT 1) to confirm the connection pool
    is working. Returns 200 if healthy, 503 if the DB is unreachable.

    Kubernetes readiness probes should target this endpoint.
    """
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        logger = get_logger(__name__)
        logger.error("readiness_check_failed")
        return JSONResponse(  # type: ignore[return-value]
            status_code=503,
            content={"status": "unavailable", "detail": "Database connection failed."},
        )
