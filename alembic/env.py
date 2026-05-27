"""
Alembic environment configuration.

Key design decisions:
1. The database URL is read from app.core.config.settings — never from
   alembic.ini — so .env is the single source of truth.
2. We use run_async_migrations() with asyncio.run() because the async
   engine (asyncpg) cannot be used with Alembic's default sync runner.
3. All ORM models are imported before Base.metadata is referenced so
   that autogenerate can discover every table.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

import app.models.repository  # noqa: F401
from alembic import context
from app.core.config import settings
from app.db.base import Base

# app.models.repository is imported above so its tables are registered on
# Base.metadata before autogenerate inspects it. Missing an import = missing
# table in migration.

# ---------------------------------------------------------------------------
# Alembic Config object — gives access to values in alembic.ini
# ---------------------------------------------------------------------------
config = context.config

# Set up Python logging from alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object autogenerate will compare against
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migrations (generate SQL without a live DB connection)
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Useful for generating a SQL script to review before applying,
    or in environments where a DB connection is not available at
    migration-generation time.
    """
    context.configure(
        url=str(settings.database_url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Emit TIMESTAMPTZ instead of TIMESTAMP for timezone-aware columns
        render_as_batch=False,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations (apply directly against a live DB connection)
# ---------------------------------------------------------------------------

async def run_async_migrations() -> None:
    """
    Create an async engine and run migrations within a sync connection
    context (Alembic's run_sync bridges the async/sync boundary).

    asyncpg does not support Alembic's default synchronous connection
    interface, so we must use this async pattern.
    """
    connectable = create_async_engine(
        str(settings.database_url),
        # No connection pooling for migrations — each migration run is
        # short-lived and disposable.
        poolclass=None,  # type: ignore[arg-type]
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations_sync)

    await connectable.dispose()


def _run_migrations_sync(connection: object) -> None:
    """Called by run_sync; receives a synchronous connection proxy."""
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Entry point for online migrations — bridges into asyncio."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
