"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_path: str = "snaplink.db"
    base_url: str = "http://localhost:8000"
    cache_capacity: int = 1024
    cache_ttl_seconds: float = 300.0
    rate_limit_capacity: int = 20
    rate_limit_refill_per_sec: float = 5.0
    code_length_min: int = 6

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_path=os.getenv("SNAPLINK_DB_PATH", cls.database_path),
            base_url=os.getenv("SNAPLINK_BASE_URL", cls.base_url).rstrip("/"),
            cache_capacity=int(os.getenv("SNAPLINK_CACHE_CAPACITY", cls.cache_capacity)),
            cache_ttl_seconds=float(os.getenv("SNAPLINK_CACHE_TTL", cls.cache_ttl_seconds)),
            rate_limit_capacity=int(os.getenv("SNAPLINK_RL_CAPACITY", cls.rate_limit_capacity)),
            rate_limit_refill_per_sec=float(
                os.getenv("SNAPLINK_RL_REFILL", cls.rate_limit_refill_per_sec)
            ),
        )
