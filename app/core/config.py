"""
Application configuration.

All settings are read from environment variables (or a .env file at the
project root).  Pydantic-settings handles coercion, validation, and
default values — no raw os.getenv() calls elsewhere in the codebase.
"""

from pydantic import AnyHttpUrl, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_name: str = "github-metadata-service"
    app_env: str = Field(default="development", pattern="^(development|staging|production)$")
    debug: bool = False
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: PostgresDsn = Field(
        ...,
        description=(
            "Async PostgreSQL connection string. "
            "Must use the asyncpg driver scheme: "
            "postgresql+asyncpg://user:password@host:port/dbname"
        ),
    )

    # Connection pool tuning — sane defaults for a single-service deployment
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=100)
    db_pool_timeout: int = Field(default=30, ge=1)  # seconds

    # ------------------------------------------------------------------
    # GitHub API
    # ------------------------------------------------------------------
    github_api_base_url: AnyHttpUrl = AnyHttpUrl("https://api.github.com")
    github_token: str | None = Field(
        default=None,
        description=(
            "Personal access token for GitHub API. "
            "Optional but strongly recommended to avoid the 60 req/hr "
            "unauthenticated rate limit."
        ),
    )
    github_request_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Timeout in seconds for each GitHub API request.",
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("database_url", mode="before")
    @classmethod
    def validate_async_driver(cls, v: str) -> str:
        """Ensure the database URL uses the asyncpg driver scheme."""
        if isinstance(v, str) and not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "database_url must use the asyncpg driver: "
                "postgresql+asyncpg://user:password@host:port/dbname"
            )
        return v


# Module-level singleton — import this instance everywhere.
# It is instantiated once at import time; environment variables are read then.
settings = Settings()
