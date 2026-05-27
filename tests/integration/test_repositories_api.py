"""
Integration tests for the Repository API endpoints.

These tests exercise the full request/response cycle:
  HTTP request → FastAPI routing → service layer → repository layer → test DB

External GitHub API calls are intercepted by respx so no real network
traffic occurs. Each test receives its own isolated engine (see conftest.py)
so no TRUNCATE fixture is needed — the schema is dropped and recreated fresh
per test, eliminating all asyncpg pool-reuse races.

Status code coverage:
  POST   → 201, 409, 422
  GET    → 200, 404
  PUT    → 200, 404
  DELETE → 204, 404
  Error propagation → 502 (GitHub upstream error), 503 (connectivity failure)
"""

import httpx

from tests.conftest import GITHUB_DJANGO_RESPONSE, GITHUB_FASTAPI_RESPONSE

# Base URL for all API routes under test
BASE = "/api/v1/repositories"


# ---------------------------------------------------------------------------
# POST /repositories — create
# ---------------------------------------------------------------------------

class TestCreateRepository:
    async def test_201_on_new_repository(self, client, mock_github_api):
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(200, json=GITHUB_FASTAPI_RESPONSE)
        )

        response = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["github_id"] == 116195547
        assert body["owner"] == "tiangolo"
        assert body["repo_name"] == "fastapi"
        assert body["full_name"] == "tiangolo/fastapi"
        assert body["stars"] == 75000
        assert body["language"] == "Python"
        assert "id" in body
        assert "created_at" in body
        assert "last_fetched_at" in body

    async def test_409_on_duplicate_submission(self, client, mock_github_api):
        """Submitting the same repository URL twice must return 409, not 201."""
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(200, json=GITHUB_FASTAPI_RESPONSE)
        )

        first = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )
        assert first.status_code == 201
        existing_id = first.json()["id"]

        second = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )

        assert second.status_code == 409
        body = second.json()
        assert body["error"] == "repository_already_exists"
        assert body["existing_id"] == existing_id

    async def test_422_on_non_github_url(self, client):
        """Pydantic validation catches wrong domain before GitHub is called."""
        response = await client.post(
            BASE, json={"github_url": "https://gitlab.com/owner/repo"}
        )

        assert response.status_code == 422
        body = response.json()
        assert body["error"] == "validation_error"

    async def test_422_on_missing_repo_path(self, client):
        """Profile URL with no repo name is rejected at schema validation."""
        response = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo"}
        )

        assert response.status_code == 422

    async def test_422_on_missing_body(self, client):
        """Request with no body must return 422, not 500."""
        response = await client.post(BASE, json={})
        assert response.status_code == 422

    async def test_404_when_github_returns_404(self, client, mock_github_api):
        mock_github_api.get("/repos/nobody/doesnotexist").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        response = await client.post(
            BASE, json={"github_url": "https://github.com/nobody/doesnotexist"}
        )

        assert response.status_code == 404
        assert response.json()["error"] == "github_repository_not_found"

    async def test_502_when_github_returns_server_error(self, client, mock_github_api):
        """GitHub responding with 500 must produce 502 from our API."""
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(500, json={"message": "Internal Server Error"})
        )

        response = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )

        assert response.status_code == 502
        assert response.json()["error"] == "github_upstream_error"

    async def test_503_when_github_times_out(self, client, mock_github_api):
        """Timeout/network failure must produce 503, distinct from 502."""
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            side_effect=httpx.TimeoutException("timed out")
        )

        response = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )

        assert response.status_code == 503
        assert response.json()["error"] == "github_service_unavailable"

    async def test_503_when_github_is_unreachable(self, client, mock_github_api):
        """Connection failure must also produce 503."""
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        response = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )

        assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /repositories/{id} — retrieve by ID
# ---------------------------------------------------------------------------

class TestGetRepository:
    async def test_200_on_existing_repository(self, client, mock_github_api):
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(200, json=GITHUB_FASTAPI_RESPONSE)
        )
        created = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )
        repo_id = created.json()["id"]

        response = await client.get(f"{BASE}/{repo_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == repo_id
        assert body["full_name"] == "tiangolo/fastapi"

    async def test_404_on_missing_repository(self, client):
        response = await client.get(f"{BASE}/99999")
        assert response.status_code == 404
        assert response.json()["error"] == "repository_not_found"


# ---------------------------------------------------------------------------
# GET /repositories — list with pagination
# ---------------------------------------------------------------------------

class TestListRepositories:
    async def test_200_returns_empty_list_initially(self, client):
        response = await client.get(BASE)

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["page"] == 1

    async def test_200_returns_all_stored_repositories(self, client, mock_github_api):
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(200, json=GITHUB_FASTAPI_RESPONSE)
        )
        mock_github_api.get("/repos/django/django").mock(
            return_value=httpx.Response(200, json=GITHUB_DJANGO_RESPONSE)
        )

        await client.post(BASE, json={"github_url": "https://github.com/tiangolo/fastapi"})
        await client.post(BASE, json={"github_url": "https://github.com/django/django"})

        response = await client.get(BASE)

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    async def test_pagination_parameters_respected(self, client, mock_github_api):
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(200, json=GITHUB_FASTAPI_RESPONSE)
        )
        mock_github_api.get("/repos/django/django").mock(
            return_value=httpx.Response(200, json=GITHUB_DJANGO_RESPONSE)
        )

        await client.post(BASE, json={"github_url": "https://github.com/tiangolo/fastapi"})
        await client.post(BASE, json={"github_url": "https://github.com/django/django"})

        response = await client.get(BASE, params={"page": 1, "page_size": 1})

        body = response.json()
        assert body["total"] == 2
        assert len(body["items"]) == 1
        assert body["page"] == 1
        assert body["page_size"] == 1


# ---------------------------------------------------------------------------
# PUT /repositories/{id} — refresh from GitHub
# ---------------------------------------------------------------------------

class TestRefreshRepository:
    async def test_200_with_updated_data(self, client, mock_github_api):
        # Seed the DB with an initial record
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(200, json=GITHUB_FASTAPI_RESPONSE)
        )
        created = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )
        repo_id = created.json()["id"]

        # Simulate GitHub data changing between the initial fetch and the refresh
        updated_response = {**GITHUB_FASTAPI_RESPONSE, "stargazers_count": 80000}
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(200, json=updated_response)
        )

        response = await client.put(f"{BASE}/{repo_id}")

        assert response.status_code == 200
        assert response.json()["stars"] == 80000

    async def test_404_when_local_record_missing(self, client):
        response = await client.put(f"{BASE}/99999")
        assert response.status_code == 404
        assert response.json()["error"] == "repository_not_found"

    async def test_502_when_github_errors_during_refresh(self, client, mock_github_api):
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(200, json=GITHUB_FASTAPI_RESPONSE)
        )
        created = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )
        repo_id = created.json()["id"]

        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(500, json={"message": "Server Error"})
        )

        response = await client.put(f"{BASE}/{repo_id}")
        assert response.status_code == 502


# ---------------------------------------------------------------------------
# DELETE /repositories/{id}
# ---------------------------------------------------------------------------

class TestDeleteRepository:
    async def test_204_on_successful_delete(self, client, mock_github_api):
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(200, json=GITHUB_FASTAPI_RESPONSE)
        )
        created = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )
        repo_id = created.json()["id"]

        response = await client.delete(f"{BASE}/{repo_id}")
        assert response.status_code == 204
        assert response.content == b""  # 204 must have no body

    async def test_record_is_gone_after_delete(self, client, mock_github_api):
        """Follow-up GET after DELETE must return 404, not a stale record."""
        mock_github_api.get("/repos/tiangolo/fastapi").mock(
            return_value=httpx.Response(200, json=GITHUB_FASTAPI_RESPONSE)
        )
        created = await client.post(
            BASE, json={"github_url": "https://github.com/tiangolo/fastapi"}
        )
        repo_id = created.json()["id"]

        await client.delete(f"{BASE}/{repo_id}")
        get_response = await client.get(f"{BASE}/{repo_id}")

        assert get_response.status_code == 404

    async def test_404_on_missing_repository(self, client):
        response = await client.delete(f"{BASE}/99999")
        assert response.status_code == 404
        assert response.json()["error"] == "repository_not_found"
