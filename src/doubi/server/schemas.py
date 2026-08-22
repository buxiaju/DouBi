"""Pydantic schemas for the REST server.

These are defined at module level (not inside :func:`build_app`) so
Pydantic v2 can resolve them as proper types instead of forward
references. ``build_app`` imports them at runtime.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DownloadRequest(BaseModel):
    """Body for ``POST /api/v1/download``."""

    url: str = Field(..., min_length=1, description="The URL to download.")
