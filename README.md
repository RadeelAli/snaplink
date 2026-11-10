# SnapLink — URL Shortener Service

[![CI](https://github.com/YOUR_USERNAME/snaplink/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/snaplink/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-blue)
![Coverage](https://img.shields.io/badge/coverage-96%25-brightgreen)
![mypy](https://img.shields.io/badge/mypy-strict-blue)

A production-style URL shortener built with FastAPI. It goes beyond a CRUD demo:
it has a layered architecture, a thread-safe token-bucket rate limiter, an LRU+TTL read
cache, non-guessable short codes, link expiry, click analytics, and a full CI pipeline.

## Features

- **Shorten URLs** with optional custom aliases and expiry (TTL)
- **Non-sequential codes**: database IDs go through a multiplicative bijection before Base62 encoding, so `/abc123` doesn't reveal how many links exist or let anyone enumerate them
- **Rate limiting**: per-client token bucket (burst + steady refill), with `X-RateLimit-*` and `Retry-After` headers
- **Read-through cache**: LRU cache with per-entry TTL in front of the database for hot redirects
- **Click analytics** per link
- **Ops-ready**: health endpoint with cache metrics, multi-stage non-root Docker image, healthcheck
- **Quality gates**: 26 tests, 96% coverage, `mypy --strict`, `ruff`, CI on Python 3.11–3.13

## Architecture

```
            ┌──────────────────────────────────────────────┐
 HTTP ───▶  │ main.py        routes, rate-limit dependency,│
            │                error → status code mapping   │
            └───────────────┬──────────────────────────────┘
                            ▼
            ┌──────────────────────────────────────────────┐
            │ service.py     business rules: validation,   │
            │                expiry, cache coordination    │
            └──────┬───────────────────────┬───────────────┘
                   ▼                       ▼
         ┌──────────────────┐   ┌──────────────────────────┐
         │ cache.py         │   │ repository.py            │
         │ LRU + TTL        │   │ LinkRepository protocol  │
         └──────────────────┘   │ + SQLite implementation  │
                                └──────────────────────────┘
   codec.py (Base62 + ID obfuscation)   rate_limiter.py (token bucket)
```

Each layer depends only on the one below it. The service depends on a `LinkRepository`
**protocol**, so swapping SQLite for Postgres means adding one class, not touching business logic.

## Quick start

```bash
# Local
python -m venv .venv && source .venv/bin/activate
make install
make run              # http://localhost:8000/docs

# Docker
docker compose up --build
```

## API

| Method   | Path                  | Description                       |
|----------|-----------------------|-----------------------------------|
| `POST`   | `/api/v1/links`       | Create a short link               |
| `GET`    | `/{code}`             | Redirect (307) to the target URL  |
| `GET`    | `/api/v1/links/{code}`| Link details + click count        |
| `DELETE` | `/api/v1/links/{code}`| Delete a link                     |
| `GET`    | `/health`             | Health + cache metrics            |

```bash
curl -X POST localhost:8000/api/v1/links \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://github.com", "ttl_seconds": 3600}'
# {"code":"k3Xq9a","short_url":"http://localhost:8000/k3Xq9a", ...}
```

Status codes: `201` created · `307` redirect · `404` unknown · `409` alias taken ·
`410` expired · `422` invalid input · `429` rate limited.

## Design decisions

**Why ID-based codes instead of random strings?**
Random codes need a collision check plus retry on every insert, and the collision rate grows
as the table fills. Deriving the code from the auto-increment ID guarantees uniqueness
for free. The multiplicative bijection (`id × M mod 62⁸`, with `M` coprime to 62) keeps the
codes non-sequential while staying fully reversible.

**Generated code vs. custom alias collisions.**
A custom alias can happen to equal a code that a future ID will generate. When that happens,
the repository deletes the row and **commits** before retrying. A `ROLLBACK` would also roll back
SQLite's `AUTOINCREMENT` counter and return the same ID again, so the retry would loop forever.
`test_generated_code_skips_collision_with_custom_code` covers this case.

**Why 307 and not 301?**
Browsers cache 301s permanently. That would break click counting, expiry and deletion.

**Why a token bucket?**
It allows short bursts (a user pasting several links) while enforcing a steady average rate.
It is O(1) per request, and idle buckets are evicted to bound memory.

**Stats bypass the cache.** Redirects are cached for speed; stats read the database so click
counts are never stale.

**Testability.** Cache, rate limiter and service accept an injectable clock, so time-based
behaviour (TTL, refill) is tested deterministically without `sleep`.

## Scaling further

The current design runs on a single node. The next steps for horizontal scale would be:

1. Move the rate limiter and cache to **Redis** (same interfaces, shared state across replicas)
2. Replace SQLite with **Postgres** through a new `LinkRepository` implementation
3. Write click events to a **queue** and aggregate asynchronously instead of `UPDATE` per click
4. Put a CDN in front of the redirect path for the most popular links

## Development

```bash
make check     # lint + typecheck + tests
make format    # auto-format
```

## Project structure

```
app/
  main.py          HTTP routes & app factory
  service.py       business logic
  repository.py    persistence (protocol + SQLite)
  cache.py         LRU cache with TTL
  rate_limiter.py  token bucket rate limiter
  codec.py         Base62 + ID obfuscation
  schemas.py       request/response models
  config.py        env-based settings
tests/
  test_units.py    unit tests (codec, cache, rate limiter, concurrency)
  test_api.py      end-to-end API tests
```

## License

MIT
