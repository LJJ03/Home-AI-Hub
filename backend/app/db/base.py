"""Shared SQLAlchemy declarative base for ORM models."""

from sqlalchemy.orm import DeclarativeBase

from app.db.metadata import metadata as shared_metadata


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    metadata = shared_metadata

