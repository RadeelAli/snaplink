"""Request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, Field


class ShortenRequest(BaseModel):
    url: AnyHttpUrl
    custom_code: str | None = Field(default=None, min_length=3, max_length=32)
    ttl_seconds: int | None = Field(default=None, gt=0, le=60 * 60 * 24 * 365)


class LinkResponse(BaseModel):
    code: str
    short_url: str
    target_url: str
    created_at: datetime
    expires_at: datetime | None


class StatsResponse(LinkResponse):
    clicks: int


class HealthResponse(BaseModel):
    status: str
    cache_size: int
    cache_hits: int
    cache_misses: int
