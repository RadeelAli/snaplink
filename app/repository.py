"""Persistence layer. The service depends on the `LinkRepository` protocol, not SQLite."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class Link:
    id: int
    code: str
    target_url: str
    created_at: datetime
    expires_at: datetime | None
    clicks: int = 0

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at


class CodeAlreadyExistsError(Exception):
    pass


class LinkRepository(Protocol):
    def create(
        self, target_url: str, expires_at: datetime | None, custom_code: str | None
    ) -> Link: ...
    def get_by_code(self, code: str) -> Link | None: ...
    def increment_clicks(self, code: str) -> None: ...
    def delete(self, code: str) -> bool: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT UNIQUE,
    target_url  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    clicks      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_links_code ON links(code);
"""


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class SQLiteLinkRepository:
    _MAX_GENERATION_ATTEMPTS = 5

    def __init__(self, path: str, code_factory: Callable[[int], str]) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()
        self._code_factory = code_factory

    def create(self, target_url: str, expires_at: datetime | None, custom_code: str | None) -> Link:
        now = datetime.now(UTC)
        params = (target_url, now.isoformat(), expires_at.isoformat() if expires_at else None)
        with self._lock:
            if custom_code is not None:
                try:
                    cur = self._conn.execute(
                        "INSERT INTO links (code, target_url, created_at, expires_at) "
                        "VALUES (?, ?, ?, ?)",
                        (custom_code, *params),
                    )
                except sqlite3.IntegrityError as exc:
                    raise CodeAlreadyExistsError(custom_code) from exc
                assert cur.lastrowid is not None
                return Link(cur.lastrowid, custom_code, target_url, now, expires_at)

            # Generated codes derive from the row id, so a generated code can clash with an
            # earlier custom code. On a clash we delete the row but still COMMIT: a ROLLBACK
            # would also roll back the AUTOINCREMENT counter and hand us the same id again.
            for _ in range(self._MAX_GENERATION_ATTEMPTS):
                self._conn.execute("BEGIN IMMEDIATE")
                cur = self._conn.execute(
                    "INSERT INTO links (code, target_url, created_at, expires_at) "
                    "VALUES (NULL, ?, ?, ?)",
                    params,
                )
                row_id = cur.lastrowid
                assert row_id is not None
                code = self._code_factory(row_id)
                try:
                    self._conn.execute("UPDATE links SET code = ? WHERE id = ?", (code, row_id))
                except sqlite3.IntegrityError:
                    self._conn.execute("DELETE FROM links WHERE id = ?", (row_id,))
                    self._conn.execute("COMMIT")
                    continue
                self._conn.execute("COMMIT")
                return Link(row_id, code, target_url, now, expires_at)
            raise RuntimeError("could not allocate a unique short code")

    def get_by_code(self, code: str) -> Link | None:
        row = self._conn.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
        if row is None:
            return None
        return Link(
            id=row["id"],
            code=row["code"],
            target_url=row["target_url"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=_parse_dt(row["expires_at"]),
            clicks=row["clicks"],
        )

    def increment_clicks(self, code: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE links SET clicks = clicks + 1 WHERE code = ?", (code,))

    def delete(self, code: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM links WHERE code = ?", (code,))
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
