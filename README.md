# GitHub Metadata Service

[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![pytest](https://img.shields.io/badge/tested%20with-pytest-0a9edc?logo=pytest&logoColor=white)](https://pytest.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Docker](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An async REST API that accepts GitHub repository URLs, fetches metadata from the GitHub REST API, and persists it in PostgreSQL. Built with FastAPI, async SQLAlchemy, and httpx.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Quick Start](#quick-start)
3. [Architecture](#architecture)
4. [Tech Stack](#tech-stack)
5. [Project Structure](#project-structure)
6. [Prerequisites](#prerequisites)
7. [Setup](#setup)
8. [Environment Variables](#environment-variables)
9. [Running Locally](#running-locally)
10. [Running with Docker Compose](#running-with-docker-compose)
11. [Database Migrations](#database-migrations)
12. [API Reference](#api-reference)
13. [Error Handling](#error-handling)
14. [Continuous Integration](#continuous-integration)
15. [Testing](#testing)
16. [Design Decisions](#design-decisions)
17. [Assumptions](#assumptions)
18. [Troubleshooting](#troubleshooting)
19. [Future Improvements](#future-improvements)

---

## Project Overview

This service provides CRUD endpoints for GitHub repository metadata. Submitting a GitHub URL triggers a live fetch from the GitHub API; the result is validated, stored in PostgreSQL, and returned to the caller. Subsequent reads are served from the local database without hitting GitHub.

The project is structured as a production-oriented backend service: fully async, layered architecture, typed throughout, and covered by unit and integration tests.

---

## Quick Start

The fastest path to a running service:

```bash
# Clone and start (PostgreSQL + migrations + API server — all-in-one)
docker compose up --build

```
To run the test suite (requires a separate test database — see [Testing](#testing)):

```bash
pytest -v
```

---

## Architecture

The codebase follows a strict three-layer architecture. Layers only communicate downward — routes call services, services call the repository layer and the GitHub client, nothing flows upward.

```
┌──────────────────────────────────────────────────────┐
│                     HTTP Client                      │
└────────────────────────┬─────────────────────────────┘
                         │  HTTP request
┌────────────────────────▼─────────────────────────────┐
│               API Layer  (app/api/)                  │
│   Route handlers — validate input, delegate to       │
│   service, return typed response. Zero logic here.   │
└────────────────────────┬─────────────────────────────┘
                         │  Domain calls
┌────────────────────────▼─────────────────────────────┐
│            Service Layer  (app/services/)             │
│   Orchestrates use cases: parse URL, fetch GitHub,   │
│   check duplicates, persist, return response schema. │
└──────────────┬──────────────────────┬────────────────┘
               │                      │
┌──────────────▼──────────┐  ┌────────▼────────────────┐
│    Repository Layer      │  │     GitHub Client        │
│  (app/repositories/)     │  │  (app/services/          │
│  Async SQLAlchemy — all  │  │   github_client.py)      │
│  DB access lives here.   │  │  httpx.AsyncClient —     │
│                          │  │  maps HTTP → exceptions. │
└──────────────┬──────────┘  └────────┬────────────────┘
               │                      │
┌──────────────▼──────────┐  ┌────────▼────────────────┐
│       PostgreSQL         │  │    GitHub REST API       │
└─────────────────────────┘  └─────────────────────────┘
```

**Exception flow:** domain exceptions (`app/core/exceptions.py`) propagate from services upward, and are mapped to HTTP status codes exclusively in `app/api/exception_handlers.py`. No layer below the API layer imports FastAPI or HTTP status codes.

---

## Tech Stack

| Component | Library | Version |
|---|---|---|
| Web framework | FastAPI | 0.115.x |
| ASGI server | Uvicorn | 0.30.x |
| ORM | SQLAlchemy (async) | 2.0.x |
| Database driver | asyncpg | 0.29.x |
| Migrations | Alembic | 1.13.x |
| Validation | Pydantic v2 | 2.7.x |
| Settings | pydantic-settings | 2.3.x |
| HTTP client | httpx | 0.27.x |
| Logging | structlog | 24.x |
| Testing | pytest + pytest-asyncio | 8.x / 0.23.x |
| HTTP mocking | respx | 0.21.x |

---

## Project Structure

```
github-metadata-service/
├── app/
│   ├── api/
│   │   ├── dependencies.py        # Typed Annotated aliases (DBSession, RepoService)
│   │   ├── exception_handlers.py  # Domain exception → HTTP status code mapping
│   │   └── v1/
│   │       └── repositories.py    # Route handlers — thin, no logic
│   ├── core/
│   │   ├── config.py              # pydantic-settings, all env vars
│   │   ├── exceptions.py          # Domain exception hierarchy
│   │   └── logging.py             # structlog configuration
│   ├── db/
│   │   ├── base.py                # SQLAlchemy DeclarativeBase
│   │   └── session.py             # Async engine, session factory, get_db_session
│   ├── models/
│   │   └── repository.py          # Repository ORM model
│   ├── schemas/
│   │   ├── github.py              # GitHub API response schema (internal)
│   │   └── repository.py          # API request/response schemas (public)
│   ├── repositories/
│   │   └── repository_repo.py     # All database access for Repository model
│   ├── services/
│   │   ├── github_client.py       # httpx.AsyncClient wrapper, exception mapping
│   │   └── repository_service.py  # Use-case orchestration
│   └── main.py                    # App factory, lifespan, health endpoints
├── alembic/
│   ├── env.py                     # Async-aware Alembic environment
│   ├── script.py.mako
│   └── versions/
│       └── 20260526_0001_create_repositories_table.py
├── tests/
│   ├── conftest.py                # Shared fixtures: engine, client, mock_github_api
│   ├── unit/
│   │   ├── test_github_url_validation.py
│   │   ├── test_repository_service.py
│   │   └── test_github_client.py
│   └── integration/
│       └── test_repositories_api.py
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

---

## Prerequisites

- Python 3.11+
- PostgreSQL 15+ (or Docker)
- pip (or uv)

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-org/github-metadata-service.git
cd github-metadata-service
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
# Production dependencies
pip install -e .

# Development dependencies (includes test tools, linter, type checker)
pip install -e ".[dev]"
```

### 4. Configure environment variables

```bash
cp .env.example .env
# Edit .env — at minimum, set DATABASE_URL and optionally GITHUB_TOKEN
```

### 5. Run database migrations

```bash
alembic upgrade head
```

---

## Environment Variables

All variables are read from a `.env` file in the project root. Copy `.env.example` to get started.

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | **Yes** | — | Async PostgreSQL connection string. Must use `postgresql+asyncpg://` scheme. |
| `GITHUB_TOKEN` | No | `""` | GitHub personal access token. Unauthenticated rate limit: 60 req/hr. Authenticated: 5,000 req/hr. |
| `APP_ENV` | No | `development` | Runtime environment. Accepted: `development`, `staging`, `production`. Controls log format (JSON in production). |
| `APP_NAME` | No | `github-metadata-service` | Service name injected into structured log output. |
| `DEBUG` | No | `false` | Enable debug mode. Do not set `true` in production. |
| `LOG_LEVEL` | No | `INFO` | Log level. Accepted: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `DB_POOL_SIZE` | No | `10` | SQLAlchemy connection pool size. |
| `DB_MAX_OVERFLOW` | No | `20` | Maximum connections above pool size. |
| `DB_POOL_TIMEOUT` | No | `30` | Seconds to wait for a connection from the pool before raising. |
| `GITHUB_API_BASE_URL` | No | `https://api.github.com` | GitHub API base URL. Override for testing against a mock server. |
| `GITHUB_REQUEST_TIMEOUT` | No | `10.0` | Per-request timeout in seconds for GitHub API calls. |
| `TEST_DATABASE_URL` | No* | `postgresql+asyncpg://postgres:postgres@localhost:5433/github_metadata_test` | Separate database for the test suite. Never points at the development DB. |

*Required when running the integration test suite.

**`DATABASE_URL` format:**

```
postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DBNAME
```

Example:
```
postgresql+asyncpg://postgres:postgres@localhost:5432/github_metadata
```

---

## Running Locally

### Start PostgreSQL

If you have Docker available:

```bash
docker run -d \
  --name github-metadata-db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=github_metadata \
  -p 5432:5432 \
  postgres:16-alpine
```

### Apply migrations

```bash
alembic upgrade head
```

### Start the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`  
Alternative docs: `http://localhost:8000/redoc`

---

## Running with Docker Compose

Docker Compose starts PostgreSQL, waits for the health check to pass, runs migrations, and starts the API server — in a single command.

```bash
# Optional: set your GitHub token to avoid rate limits
export GITHUB_TOKEN=ghp_your_token_here

docker compose up --build
```

The service is available at `http://localhost:8000` once the `app` container logs `application_startup`.

```bash
# Stop and remove containers (data volume is preserved)
docker compose down

# Stop and remove containers AND the database volume
docker compose down -v
```

---

## Database Migrations

This project uses [Alembic](https://alembic.sqlalchemy.org/) for schema migrations. The `alembic/env.py` is configured for async SQLAlchemy using the `run_sync` bridge pattern required by asyncpg.

```bash
# Apply all pending migrations
alembic upgrade head

# Roll back the most recent migration
alembic downgrade -1

# Roll back all migrations (returns to empty schema)
alembic downgrade base

# Show migration history
alembic history --verbose

# Show current applied revision
alembic current

# Generate a new migration (requires a running DB)
alembic revision --autogenerate -m "add_column_x_to_repositories"
```

> **Note:** Always review autogenerated migrations before applying. Alembic's autogenerate does not detect all changes (e.g. server defaults, some index changes).

---

## API Reference

### Base URL

```
http://localhost:8000/api/v1
```

### Endpoints

---

#### `POST /repositories`

Submit a GitHub repository URL. Fetches metadata from GitHub and stores it locally.

**Request body:**

```json
{
  "github_url": "https://github.com/tiangolo/fastapi"
}
```

**Success response — `201 Created`:**

```json
{
  "id": 1,
  "github_id": 116195547,
  "owner": "tiangolo",
  "repo_name": "fastapi",
  "full_name": "tiangolo/fastapi",
  "description": "FastAPI framework, high performance, easy to learn, fast to code",
  "html_url": "https://github.com/tiangolo/fastapi",
  "stars": 75000,
  "forks": 6100,
  "language": "Python",
  "github_created_at": "2018-12-08T08:21:47Z",
  "github_updated_at": "2024-01-15T10:00:00Z",
  "created_at": "2026-05-26T12:00:00Z",
  "last_fetched_at": "2026-05-26T12:00:00Z"
}
```

**Example:**

```bash
curl -X POST http://localhost:8000/api/v1/repositories \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/tiangolo/fastapi"}'
```

---

#### `GET /repositories`

List all stored repositories with pagination.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | integer | `1` | Page number (1-indexed) |
| `page_size` | integer | `20` | Items per page (1–100) |

**Success response — `200 OK`:**

```json
{
  "items": [
    {
      "id": 1,
      "github_id": 116195547,
      "full_name": "tiangolo/fastapi",
      "stars": 75000,
      ...
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

**Example:**

```bash
curl "http://localhost:8000/api/v1/repositories?page=1&page_size=10"
```

---

#### `GET /repositories/{id}`

Retrieve a single stored repository by its internal integer ID.

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `id` | integer | Internal database ID assigned at creation |

**Success response — `200 OK`:** (same shape as POST 201 response)

**Example:**

```bash
curl http://localhost:8000/api/v1/repositories/1
```

---

#### `PUT /repositories/{id}`

Re-fetch metadata from GitHub and update the stored record. Always calls GitHub — no caching.

**Path parameters:** same as GET `/{id}`

**Request body:** none

**Success response — `200 OK`:** (same shape as POST 201 response, with updated field values)

**Example:**

```bash
curl -X PUT http://localhost:8000/api/v1/repositories/1
```

---

#### `DELETE /repositories/{id}`

Remove a repository from the local store. Does not affect the GitHub repository.

**Success response — `204 No Content`:** empty body

**Example:**

```bash
curl -X DELETE http://localhost:8000/api/v1/repositories/1
```

---

---

### Full Lifecycle Example

The complete create → read → refresh → delete cycle for a single repository:

```bash
BASE="http://localhost:8000/api/v1/repositories"

# 1. Submit a repository URL — fetches from GitHub and stores it locally
curl -s -X POST "$BASE" \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/tiangolo/fastapi"}' | jq .

# 2. Retrieve the stored record by its local ID
curl -s "$BASE/1" | jq .

# 3. Re-fetch from GitHub and update the stored metadata
curl -s -X PUT "$BASE/1" | jq .

# 4. Delete the local record (GitHub is unaffected)
curl -s -X DELETE "$BASE/1" -w "%{http_code}\n"
# → 204
```

---

#### `GET /health`

Liveness check. Returns `200` immediately with no dependency checks.

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

#### `GET /health/ready`

Readiness check. Executes `SELECT 1` against the database. Returns `503` if the DB is unreachable.

```bash
curl http://localhost:8000/health/ready
# {"status": "ready"}
```

---

## Error Handling

All error responses follow a consistent JSON envelope:

```json
{
  "error": "machine_readable_code",
  "message": "Human-readable description."
}
```

The `409 Conflict` response additionally includes `existing_id` so the client can retrieve the conflicting record immediately:

```json
{
  "error": "repository_already_exists",
  "message": "Repository with github_id=116195547 already exists (id=1)",
  "existing_id": 1
}
```

### Status Code Reference

| Status | Trigger | Error Code |
|---|---|---|
| `201 Created` | Repository created successfully | — |
| `200 OK` | Repository found / refreshed | — |
| `204 No Content` | Repository deleted successfully | — |
| `404 Not Found` | Local record not found | `repository_not_found` |
| `404 Not Found` | GitHub repo does not exist | `github_repository_not_found` |
| `409 Conflict` | `github_id` already stored locally | `repository_already_exists` |
| `422 Unprocessable Entity` | Invalid GitHub URL or request body | `validation_error` / `invalid_github_url` |
| `429 Too Many Requests` | GitHub rate limit exceeded | `github_rate_limit_exceeded` |
| `500 Internal Server Error` | Unhandled server fault | `internal_server_error` |
| `502 Bad Gateway` | GitHub returned an error HTTP response | `github_upstream_error` |
| `503 Service Unavailable` | GitHub unreachable (timeout / network) | `github_service_unavailable` |

The `502` / `503` distinction is intentional. `502` means GitHub responded but negatively. `503` means the service could not establish a connection at all. These require different retry strategies on the client side.

When GitHub returns `429` or a rate-limit `403`, the response includes a `Retry-After` header when GitHub provided one:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 3600
```

---

## Continuous Integration

A GitHub Actions workflow (`.github/workflows/test.yml`) runs automatically on every push and pull request to `main`.

The pipeline:

1. **Spins up a PostgreSQL 16 service container** — no external database required in CI.
2. **Runs `ruff check .`** — the build fails immediately on any lint error.
3. **Runs `pytest tests/unit/`** — unit tests only (no DB dependency, fast feedback).
4. **Runs `pytest tests/integration/`** — full stack tests against the CI PostgreSQL instance.

The integration test suite creates and destroys the schema automatically per test — no manual migration step is needed in CI. Both `DATABASE_URL` and `TEST_DATABASE_URL` are injected as environment variables by the workflow.

---

## Testing

### Test setup

The integration test suite requires a separate PostgreSQL database. The test engine creates and tears down the schema automatically — no manual migration step is needed.

```bash
# Create the test database (one-time setup)
createdb github_metadata_test

# Or with Docker (if using the docker-compose DB on port 5433)
docker exec -it github-metadata-service-db-1 psql -U postgres \
  -c "CREATE DATABASE github_metadata_test;"
```

Set the test database URL if it differs from the default (port `5433` when using docker-compose):

```bash
export TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/github_metadata_test"
```

### Run all tests

```bash
pytest
```

### Run with verbose output

```bash
pytest -v
```

### Run only unit tests (no database required)

```bash
pytest tests/unit/
```

### Run only integration tests

```bash
pytest tests/integration/
```

### Lint

```bash
ruff check .
```

### Coverage report

Coverage is enabled by default via `pyproject.toml`. An HTML report is generated at `htmlcov/index.html` after each run.

```bash
pytest --cov=app --cov-report=html
open htmlcov/index.html
```

---

### Test architecture

#### Unit tests (`tests/unit/`)

Unit tests have zero external dependencies — no database, no network.

- **`test_github_url_validation.py`** — Tests `RepositoryCreateRequest` Pydantic validation: valid URLs, wrong host, wrong path structure. Exercises only the schema class.

- **`test_repository_service.py`** — Tests `RepositoryService` orchestration with `AsyncMock` replacing both the GitHub client and the repository layer. Verifies field mapping, duplicate detection, not-found handling, and that GitHub is called before the duplicate check (so `github_id`, not the URL, is the uniqueness anchor).

- **`test_github_client.py`** — Tests `GitHubClient` exception translation using `respx` to intercept httpx at the transport level. Covers 404→`GitHubNotFoundError`, 429→`GitHubRateLimitError`, 5xx→`GitHubUpstreamError`, timeout→`GitHubConnectivityError`, and connect error→`GitHubConnectivityError`.

#### Integration tests (`tests/integration/`)

Integration tests exercise the full stack: HTTP request → FastAPI routing → service → repository layer → PostgreSQL.

- **`test_repositories_api.py`** — Covers all five endpoints (POST, GET, GET list, PUT, DELETE) for both success and error paths. Validates exact status codes, response body shape, and state changes (e.g. record is gone after DELETE).

#### Key test infrastructure

**Per-test database isolation:** Each integration test receives its own isolated async engine (`test_engine` fixture, function-scoped). `Base.metadata.drop_all` followed by `create_all` runs before every test, giving each test a completely clean schema with a fresh auto-increment sequence. No TRUNCATE fixture is needed — schema recreation is the isolation boundary.

**async fixtures:** All async fixtures use the `@pytest_asyncio.fixture` decorator rather than `@pytest.fixture`. This is required by pytest-asyncio 0.23 to correctly schedule async generator teardown within the asyncio event loop.

**respx mocking:** The `mock_github_api` fixture activates `respx.mock` for `https://api.github.com`, intercepting httpx requests at the transport level before any socket is opened. `assert_all_called=False` allows tests that fail at the validation layer (e.g. `422` tests) to register mock routes without requiring them to be called.

**ASGI client:** Integration tests use `httpx.AsyncClient` with `httpx.ASGITransport(app=app)` rather than the deprecated `app=` kwarg. This correctly handles the FastAPI lifespan boundary and avoids pending task errors on teardown.

**Dependency override:** The `client` fixture overrides `get_db_session` via `app.dependency_overrides` to inject sessions bound to the per-test engine. The service layer owns transaction commits; the override simply yields the session. Overrides are cleared after each test.

---

## Design Decisions

### Fully async architecture

FastAPI runs on an asyncio event loop. A synchronous database driver or HTTP client would block the event loop for the duration of each I/O operation, preventing the server from handling other requests during that wait. `asyncpg` (native async PostgreSQL driver) and `httpx.AsyncClient` ensure I/O operations yield control back to the event loop immediately, allowing the server to remain responsive under concurrent load without additional threads.

### Service / repository separation

The repository layer (`app/repositories/`) contains only database access code. The service layer (`app/services/`) contains only orchestration logic. This separation has a concrete benefit for testing: the repository layer can be replaced with an `AsyncMock` in service unit tests, exercising all business logic without a database connection. Conversely, repository methods can be tested against a real database without involving the GitHub client. If the separation were collapsed (queries inside service methods), both concerns would have to be tested together, which requires every combination of external state to be set up.

### Typed schemas over raw dicts

The `GitHubRepoSchema` models exactly what the GitHub API returns. When `model_validate(response.json())` succeeds, the caller receives a typed object with documented nullable fields — not a dict where any key access could be a `KeyError`. Validation failures are raised immediately at the API boundary rather than propagating as `AttributeError` or `KeyError` deep in the call stack. The `RepositoryResponse` schema is separately defined from the GitHub schema and the ORM model, so each can evolve independently without a breaking change to the others.

### Centralized exception handling

All domain exceptions (`app/core/exceptions.py`) are pure Python classes with no HTTP coupling. A single registration function (`register_exception_handlers`) maps each exception type to a status code and error envelope. This means: every `RepositoryNotFoundError` anywhere in the application produces an identical `404` response; adding a new endpoint requires zero new error-handling code if it uses existing exception types; and the service layer is fully testable without a running HTTP server.

### Database-level uniqueness constraint

`UNIQUE (github_id)` in PostgreSQL enforces uniqueness even under concurrent requests. If two requests with the same GitHub URL arrive simultaneously, both may pass the service-layer duplicate check (which is a read-then-write, not atomic), but only one can succeed at the database level. The other receives an integrity error that the service maps to `RepositoryAlreadyExistsError`. Pydantic validation and service-layer checks provide better error messages earlier; the database constraint is the actual correctness guarantee.

### `github_id` as the uniqueness anchor

GitHub repository URLs can change (repos can be renamed or transferred to a different owner). The `github_id` integer is assigned at repository creation and never changes. Using `full_name` or URL as the uniqueness key would create silent duplicates after a rename. Using `github_id` means the system correctly identifies the same repository regardless of what it's called today.

### Integer auto-increment primary keys

The assessment explicitly requires database-assigned integer IDs. Integer PKs are also index-friendly, sort naturally (most recent = highest ID), and are straightforward to reason about in queries and tests.

---

## Assumptions

- **Public repositories only.** The service fetches metadata using the GitHub API's public endpoint. Private repositories would require user OAuth tokens, which is out of scope.
- **No refresh caching.** `PUT /{id}` always calls GitHub. There is no staleness threshold. A production system might add a `min_refresh_interval` to protect the GitHub rate limit under high PUT traffic.
- **No soft deletes.** `DELETE /{id}` permanently removes the record. Soft-delete or audit logging would require an additional schema change.
- **Single-region deployment.** No multi-region or read-replica considerations. The connection pool settings assume a single PostgreSQL instance.
- **GitHub token is optional.** Without a token the API is rate-limited to 60 requests per hour. For any real usage, a personal access token should be set via `GITHUB_TOKEN`. No special scopes are required for public repository metadata.
- **Repo renames are not reconciled.** If a stored repository is renamed or transferred on GitHub, the local record will retain the old `owner` and `repo_name`. The `github_id` remains correct, but the `PUT` refresh would need to be extended to update identity fields. This is a known limitation, noted in `repository_repo.py`.

---

## Troubleshooting

### `MissingGreenlet` error at startup or during tests

This indicates a synchronous SQLAlchemy operation is being called in an async context (or vice versa). Check that:
- The database URL starts with `postgresql+asyncpg://`, not `postgresql://`.
- All SQLAlchemy queries use `await session.execute(...)`, not `session.execute(...)`.
- You are not accessing ORM attributes outside an active session after `expire_on_commit=True` (the default). `session.py` sets `expire_on_commit=False` to prevent this.

### `sqlalchemy.exc.InterfaceError: connection is closed`

The connection pool timed out or the PostgreSQL server restarted. Verify `DATABASE_URL` is correct and PostgreSQL is reachable. The pool settings (`DB_POOL_TIMEOUT`) may need tuning for your environment.

### `422 Unprocessable Entity` on POST with a valid-looking URL

The URL validator checks both the host (`github.com` or `www.github.com`) and the path structure (exactly two non-empty segments: `/{owner}/{repo}`). URLs with additional path segments (e.g. `/tiangolo/fastapi/issues`) are rejected. Ensure the URL points to the repository root.

### GitHub rate limit errors (`429`)

Set a `GITHUB_TOKEN` in your `.env` file. Unauthenticated requests are limited to 60/hr per IP; authenticated requests have a 5,000/hr limit. Create a token at [github.com/settings/tokens](https://github.com/settings/tokens) — no scopes are required for public metadata.

### Alembic `Target database is not up to date`

Run `alembic upgrade head` to apply all pending migrations before starting the server.

### Tests fail with `asyncpg.exceptions.InvalidCatalogNameError`

The test database does not exist. Create it:

```bash
createdb github_metadata_test
# or
psql -U postgres -c "CREATE DATABASE github_metadata_test;"
```

### `respx.MockTransport` not intercepting requests

If a test hits the real GitHub API instead of the mock, ensure the `mock_github_api` fixture is listed as a parameter in the test function. `respx.mock` is only active within the fixture's scope.

---

## Future Improvements

**Authentication and multi-user support.** The current API is unprotected. Adding API key or JWT-based authentication would be required before any public deployment.

**Webhook-based metadata sync.** Instead of requiring clients to `PUT /{id}` to refresh, the service could subscribe to GitHub webhooks to receive push and metadata events and update records automatically.

**Background refresh scheduling.** A periodic task (e.g. via APScheduler or an external job queue like Celery/ARQ) could refresh stale records automatically based on `last_fetched_at`.

**Rate limit awareness.** The GitHub client could check the `X-RateLimit-Remaining` header on each response and proactively back off before the limit is exhausted, rather than only handling `429` after the fact.

**Pagination cursor support.** The current pagination uses `OFFSET/LIMIT`, which is inefficient at high page numbers on large tables. Cursor-based pagination (keyset pagination on `id`) would scale better.

**Soft deletes and audit log.** For a production system, hard deletes are often undesirable. An `is_deleted` flag plus a separate audit table would provide record history.

**Structured request ID tracing.** Adding a `X-Request-ID` middleware that injects a UUID per request into the structlog context would make distributed log tracing straightforward without a full APM stack.

**Repository rename reconciliation.** On `PUT /{id}`, if the GitHub API returns a `full_name` that differs from what is stored, the local `owner`, `repo_name`, and `full_name` fields should be updated to reflect the rename.
