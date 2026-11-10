"""Business logic: validation, caching and expiry rules. Framework-agnostic."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.cache import LRUCache
from app.codec import is_valid_code
from app.repository import CodeAlreadyExistsError, Link, LinkRepository

RESERVED_CODES = frozenset({"api", "health", "docs", "openapi", "redoc", "metrics"})


class LinkNotFoundError(Exception):
    pass


class LinkExpiredError(Exception):
    pass


class InvalidCodeError(ValueError):
    pass


class CodeTakenError(Exception):
    pass


class LinkService:
    def __init__(
        self,
        repo: LinkRepository,
        cache: LRUCache[str, Link],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo = repo
        self._cache = cache
        self._now = now

    def shorten(
        self,
        target_url: str,
        custom_code: str | None = None,
        ttl: timedelta | None = None,
    ) -> Link:
        if custom_code is not None:
            if not (3 <= len(custom_code) <= 32) or not is_valid_code(custom_code):
                raise InvalidCodeError("custom code must be 3-32 alphanumeric characters")
            if custom_code.lower() in RESERVED_CODES:
                raise InvalidCodeError(f"'{custom_code}' is reserved")
        expires_at = self._now() + ttl if ttl else None
        try:
            link = self._repo.create(target_url, expires_at, custom_code)
        except CodeAlreadyExistsError as exc:
            raise CodeTakenError(custom_code) from exc
        self._cache.put(link.code, link)
        return link

    def resolve(self, code: str) -> Link:
        """Look up a code for redirection and record the click."""
        link = self._lookup(code)
        self._repo.increment_clicks(code)
        return link

    def stats(self, code: str) -> Link:
        # Stats bypass the cache so click counts are always fresh.
        link = self._repo.get_by_code(code)
        if link is None:
            raise LinkNotFoundError(code)
        return link

    def delete(self, code: str) -> None:
        self._cache.invalidate(code)
        if not self._repo.delete(code):
            raise LinkNotFoundError(code)

    def _lookup(self, code: str) -> Link:
        if not is_valid_code(code):
            raise LinkNotFoundError(code)
        link = self._cache.get(code)
        if link is None:
            link = self._repo.get_by_code(code)
            if link is None:
                raise LinkNotFoundError(code)
            self._cache.put(code, link)
        if link.is_expired(self._now()):
            self._cache.invalidate(code)
            raise LinkExpiredError(code)
        return link
