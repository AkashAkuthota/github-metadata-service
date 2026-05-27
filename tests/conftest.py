"""
Shared pytest fixtures for all test layers.
"""

import os
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.db.session import get_db_session
from app.main import app

# ---------------------------------------------------------------------------
# Test database
# ---------------------------------------------------------------------------

TEST_DATABASE_URL: str = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/github_metadata_test",
)

# ---------------------------------------------------------------------------
# Mock GitHub responses
# ---------------------------------------------------------------------------

GITHUB_FASTAPI_RESPONSE: dict = {
    "id": 116195547,
    "name": "fastapi",
    "full_name": "tiangolo/fastapi",
    "owner": {"login": "tiangolo"},
    "description": "FastAPI framework, high performance, easy to learn, fast to code",
    "html_url": "https://github.com/tiangolo/fastapi",
    "stargazers_count": 75000,
    "forks_count": 6100,
    "language": "Python",
    "created_at": "2018-12-08T08:21:47Z",
    "updated_at": "2024-01-15T10:00:00Z",
}

GITHUB_DJANGO_RESPONSE: dict = {
    "id": 4164482,
    "name": "django",
    "full_name": "django/django",
    "owner": {"login": "django"},
    "description": "The Web framework for perfectionists with deadlines.",
    "html_url": "https://github.com/django/django",
    "stargazers_count": 78000,
    "forks_count": 31000,
    "language": "Python",
    "created_at": "2012-04-28T02:47:18Z",
    "updated_at": "2024-01-15T09:00:00Z",
}

# ---------------------------------------------------------------------------
# Async engine — function-scoped: each test gets a fresh engine and pool.
#
# Using a session-scoped engine causes asyncpg pool corruption across the
# FastAPI ASGI lifespan boundary: connections returned to the pool by one
# test's request may still be mid-operation when the next test's fixture
# teardown (TRUNCATE) fires, producing:
#     InterfaceError: cannot perform operation: another operation is in progress
#
# A function-scoped engine drops/recreates tables per test. This is slower
# but eliminates all pool-reuse races and requires no TRUNCATE fixture.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_engine():
    """
    Create an isolated async engine for each test.

    Drops and recreates all tables on entry; disposes the engine on exit.
    Each test starts with a completely clean schema and its own connection pool.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


# ---------------------------------------------------------------------------
# DB session fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Raw AsyncSession for repository-layer tests that inspect DB state directly.
    """
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# HTTP client fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """
    httpx.AsyncClient wired to the FastAPI app with the test DB injected.

    The dependency override redirects get_db_session to the per-test engine.
    The override is cleared after each test to prevent bleed between tests.

    The service layer owns transaction lifecycle (commit/rollback); the
    override intentionally does nothing beyond yielding the session.
    """
    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = httpx.ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GitHub API mock
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_github_api():
    """
    Activate respx mock for all requests to api.github.com.

    assert_all_called=False allows tests to register routes they may or
    may not hit without failing tests that never reach the GitHub call
    (e.g. 422 validation tests that fail at the schema layer).
    """
    with respx.mock(
        base_url="https://api.github.com",
        assert_all_called=False,
    ) as mock:
        yield mock
