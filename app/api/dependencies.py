"""
FastAPI dependency definitions.

Typed `Annotated` aliases keep route handler signatures concise:

    async def my_route(
        session: DBSession,
        service: RepoService,
    ) -> ...:

instead of repeating `Depends(...)` inline on every route.

All application-level singletons (service, db session factory) are
wired here so routes never import implementation modules directly.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.services.repository_service import RepositoryService, repository_service


def get_repository_service() -> RepositoryService:
    """Return the application-level RepositoryService singleton."""
    return repository_service


# ------------------------------------------------------------------
# Typed dependency aliases — import these in route handlers.
# ------------------------------------------------------------------

# An AsyncSession scoped to the current request.
# Automatically committed on success, rolled back on exception.
DBSession = Annotated[AsyncSession, Depends(get_db_session)]

# The RepositoryService instance, injected as a FastAPI dependency.
# Using a Depends wrapper (rather than importing the singleton directly)
# makes it trivial to override in tests via app.dependency_overrides.
RepoService = Annotated[RepositoryService, Depends(get_repository_service)]
