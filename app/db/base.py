"""
SQLAlchemy declarative base.

All ORM models import Base from here so that Alembic's autogenerate
can discover every table through a single metadata object.

Import order matters for Alembic: models must be imported before
alembic/env.py calls Base.metadata — see alembic/env.py for details.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Project-wide declarative base.

    Using DeclarativeBase (SQLAlchemy 2.x style) rather than the legacy
    declarative_base() factory gives us full type inference on mapped
    columns without extra plugins.
    """
