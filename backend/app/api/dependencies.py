"""Reusable dependencies for API routes."""

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.session import get_db

__all__ = ["get_db", "Session", "Generator"]
