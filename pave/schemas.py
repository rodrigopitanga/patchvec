# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pydantic schemas for API request/response validation."""

from typing import Any
from pydantic import BaseModel


class SearchResult(BaseModel):
    """API response item for search results."""
    id: str
    score: float
    text: str | None
    tenant: str
    collection: str
    meta: dict[str, Any]
    match_reason: str


class SearchResponse(BaseModel):
    """API response for search endpoints."""
    matches: list[SearchResult]
    latency_ms: float | None = None
    request_id: str | None = None


class SearchBody(BaseModel):
    """API request body for search endpoints."""
    q: str
    k: int = 5
    filters: dict[str, Any] | None = None
    request_id: str | None = None


class RenameCollectionBody(BaseModel):
    """API request body for collection rename."""
    new_name: str
