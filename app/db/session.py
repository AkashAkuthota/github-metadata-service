"""
Async database engine and session management.

Provides:
- `engine`         — module-level async engine (created once at startup)
- `AsyncSessionLocal` — async_sessionmaker bound to the engine
- `get_db_session` — FastAPI dependency that yields a session per request

Lifecycle:
  The engine is initialised at module import time using settings.
  For production use, the FastAPI lifespan context (main.py) disposes
  the engine on shutdown to close all pooled connections gracefully.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# echo=False in all environments — SQL logging should go through the
# structlog pipeline, not SQLAlchemy's built-in echo which bypasses it.
engine: AsyncEngine = create_async_engine(
    str(settings.database_url),
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    # asyncpg returns timezone-aware datetimes; this keeps SQLAlchemy aligned.
    connect_args={"server_settings": {"timezone": "UTC"}},
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
# async_sessionmaker (SQLAlchemy 2.x) is preferred over the older
# sessionmaker() because it correctly types the returned AsyncSession and
# avoids the greenlet_spawn compatibility shim needed by the legacy factory.
#
# expire_on_commit=False: after a commit, ORM objects remain accessible
# without issuing additional SELECT queries. This is important in async
# code where lazy-loading is not available — accessing an expired attribute
# after commit would raise MissingGreenlet.
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a database session for the duration of a single request.

    Usage in route handlers:
        async def my_route(session: AsyncSession = Depends(get_db_session)):
            ...

    Transaction ownership: the SERVICE LAYER is responsible for calling
    session.commit() after successful mutations and for raising exceptions
    that signal failure. This dependency only provides and closes the session.

    The async context manager on AsyncSessionLocal handles session.close()
    automatically on exit — whether the request succeeds or raises.
    """
    async with AsyncSessionLocal() as session:
        yield session
