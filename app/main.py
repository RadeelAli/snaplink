"""HTTP layer: wiring, routes and error mapping."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.cache import LRUCache
from app.codec import id_to_code
from app.config import Settings
from app.rate_limiter import TokenBucketRateLimiter
from app.repository import Link, SQLiteLinkRepository
from app.schemas import HealthResponse, LinkResponse, ShortenRequest, StatsResponse
from app.service import (
    CodeTakenError,
    InvalidCodeError,
    LinkExpiredError,
    LinkNotFoundError,
    LinkService,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    cache: LRUCache[str, Link] = LRUCache(settings.cache_capacity, settings.cache_ttl_seconds)
    repo = SQLiteLinkRepository(
        settings.database_path,
        code_factory=lambda n: id_to_code(n, settings.code_length_min),
    )
    service = LinkService(repo, cache)
    limiter = TokenBucketRateLimiter(
        settings.rate_limit_capacity, settings.rate_limit_refill_per_sec
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        repo.close()

    app = FastAPI(
        title="SnapLink",
        version="1.0.0",
        description="A production-style URL shortener with caching and rate limiting.",
        lifespan=lifespan,
    )

    def rate_limit(request: Request, response: Response) -> None:
        client = request.client.host if request.client else "unknown"
        decision = limiter.acquire(client)
        response.headers["X-RateLimit-Limit"] = str(limiter.capacity)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        if not decision.allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "rate limit exceeded",
                headers={"Retry-After": str(max(1, round(decision.retry_after)))},
            )

    def to_response(link: Link) -> LinkResponse:
        return LinkResponse(
            code=link.code,
            short_url=f"{settings.base_url}/{link.code}",
            target_url=link.target_url,
            created_at=link.created_at,
            expires_at=link.expires_at,
        )

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok", cache_size=len(cache), cache_hits=cache.hits, cache_misses=cache.misses
        )

    @app.post(
        "/api/v1/links",
        response_model=LinkResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(rate_limit)],
        tags=["links"],
    )
    def shorten(body: ShortenRequest) -> LinkResponse:
        ttl = timedelta(seconds=body.ttl_seconds) if body.ttl_seconds else None
        try:
            link = service.shorten(str(body.url), body.custom_code, ttl)
        except InvalidCodeError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        except CodeTakenError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "custom code already in use") from exc
        return to_response(link)

    @app.get("/api/v1/links/{code}", response_model=StatsResponse, tags=["links"])
    def stats(code: str) -> StatsResponse:
        try:
            link = service.stats(code)
        except LinkNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found") from exc
        return StatsResponse(**to_response(link).model_dump(), clicks=link.clicks)

    @app.delete("/api/v1/links/{code}", status_code=status.HTTP_204_NO_CONTENT, tags=["links"])
    def delete(code: str) -> Response:
        try:
            service.delete(code)
        except LinkNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found") from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/{code}", dependencies=[Depends(rate_limit)], tags=["redirect"])
    def redirect(code: str) -> RedirectResponse:
        try:
            link = service.resolve(code)
        except LinkNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found") from exc
        except LinkExpiredError as exc:
            raise HTTPException(status.HTTP_410_GONE, "link expired") from exc
        # 307 (not 301) so browsers don't cache the redirect and clicks stay countable.
        return RedirectResponse(link.target_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    return app
