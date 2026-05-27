"""
Unit tests for GitHub URL validation in RepositoryCreateRequest.

Tests the Pydantic-level (Tier 1) validation only.
No database. No network. No service layer.

Covers:
  - Valid GitHub repository URLs (various forms)
  - Wrong host rejection
  - Missing path segments rejection
  - Too many path segments rejection
"""

import pytest
from pydantic import ValidationError

from app.schemas.repository import RepositoryCreateRequest


def make_request(url: str) -> RepositoryCreateRequest:
    return RepositoryCreateRequest(github_url=url)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Valid URLs — should parse without error
# ---------------------------------------------------------------------------

class TestValidGitHubUrls:
    def test_standard_repo_url(self):
        req = make_request("https://github.com/tiangolo/fastapi")
        assert req.github_url is not None

    def test_url_with_www(self):
        """www.github.com is an accepted alias."""
        req = make_request("https://www.github.com/tiangolo/fastapi")
        assert req.github_url is not None

    def test_url_with_git_suffix(self):
        """Clone-style URLs with .git should be accepted at validation stage."""
        req = make_request("https://github.com/django/django.git")
        assert req.github_url is not None

    def test_url_with_trailing_slash(self):
        """Trailing slashes on a two-segment path are still valid."""
        req = make_request("https://github.com/tiangolo/fastapi/")
        assert req.github_url is not None


# ---------------------------------------------------------------------------
# Invalid host — should raise ValidationError
# ---------------------------------------------------------------------------

class TestInvalidHost:
    def test_gitlab_url_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            make_request("https://gitlab.com/tiangolo/fastapi")
        assert "github.com" in str(exc_info.value)

    def test_bitbucket_url_rejected(self):
        with pytest.raises(ValidationError):
            make_request("https://bitbucket.org/owner/repo")

    def test_arbitrary_domain_rejected(self):
        with pytest.raises(ValidationError):
            make_request("https://example.com/owner/repo")

    def test_github_subdomain_rejected(self):
        """Subdomains like gist.github.com are not repository URLs."""
        with pytest.raises(ValidationError):
            make_request("https://gist.github.com/owner/snippet")


# ---------------------------------------------------------------------------
# Invalid path structure — should raise ValidationError
# ---------------------------------------------------------------------------

class TestInvalidPath:
    def test_root_url_rejected(self):
        """https://github.com alone has no repository path."""
        with pytest.raises(ValidationError):
            make_request("https://github.com")

    def test_owner_only_rejected(self):
        """Profile URL — no repo name."""
        with pytest.raises(ValidationError):
            make_request("https://github.com/tiangolo")

    def test_too_many_segments_rejected(self):
        """Deep paths (e.g. file paths inside a repo) are not repo URLs."""
        with pytest.raises(ValidationError):
            make_request("https://github.com/tiangolo/fastapi/blob/master/README.md")

    def test_empty_repo_name_rejected(self):
        """A trailing slash after owner with no repo name."""
        with pytest.raises(ValidationError):
            make_request("https://github.com/tiangolo/")
