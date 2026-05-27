"""
Structured logging configuration using structlog.

Provides a single `get_logger` factory used across all layers.
In production, output is JSON; in development, output is human-readable
coloured console output.

Usage:
    from app.core.logging import get_logger
    logger = get_logger(__name__)
    logger.info("repository_fetched", owner="tiangolo", repo="fastapi", stars=75000)
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import settings


def _add_app_context(
    logger: Any,  # noqa: ANN401
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Inject constant app-level fields into every log record."""
    event_dict["app"] = settings.app_name
    event_dict["env"] = settings.app_env
    return event_dict


def configure_logging() -> None:
    """
    Configure structlog and the stdlib logging bridge.

    Call once at application startup (in main.py lifespan).
    """
    is_production = settings.app_env == "production"
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_app_context,
        structlog.processors.StackInfoRenderer(),
    ]

    if is_production:
        # JSON output — machine-readable, suitable for log aggregators
        processors: list[Processor] = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Human-readable coloured output for local development
        processors = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
    processors=processors,
    wrapper_class=structlog.make_filtering_bound_logger(log_level),
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

    # Bridge stdlib logging (e.g. uvicorn, SQLAlchemy) through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(log_level)


def get_logger(name: str) -> Any:
    """Return a bound structlog logger for the given module name."""
    return structlog.get_logger(name)
