from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(database_path=str(tmp_path / "test.db"), rate_limit_capacity=1000)
    with TestClient(create_app(settings), follow_redirects=False) as c:
        yield c


def test_shorten_and_redirect(client: TestClient) -> None:
    res = client.post("/api/v1/links", json={"url": "https://example.com/a?b=1"})
    assert res.status_code == 201
    body = res.json()
    assert body["short_url"].endswith(body["code"])
    assert len(body["code"]) >= 6

    redirect = client.get(f"/{body['code']}")
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://example.com/a?b=1"


def test_clicks_are_counted(client: TestClient) -> None:
    code = client.post("/api/v1/links", json={"url": "https://example.com"}).json()["code"]
    for _ in range(3):
        client.get(f"/{code}")
    assert client.get(f"/api/v1/links/{code}").json()["clicks"] == 3


def test_custom_code_and_conflict(client: TestClient) -> None:
    payload = {"url": "https://example.com", "custom_code": "myLink"}
    assert client.post("/api/v1/links", json=payload).status_code == 201
    assert client.post("/api/v1/links", json=payload).status_code == 409


@pytest.mark.parametrize("bad", ["has space", "api", "dash-ed"])
def test_invalid_custom_codes_rejected(client: TestClient, bad: str) -> None:
    res = client.post("/api/v1/links", json={"url": "https://example.com", "custom_code": bad})
    assert res.status_code == 422


def test_invalid_url_rejected(client: TestClient) -> None:
    assert client.post("/api/v1/links", json={"url": "not-a-url"}).status_code == 422


def test_unknown_code_returns_404(client: TestClient) -> None:
    assert client.get("/doesNotExist").status_code == 404


def test_expired_link_returns_410(client: TestClient) -> None:
    code = client.post(
        "/api/v1/links", json={"url": "https://example.com", "ttl_seconds": 1}
    ).json()["code"]
    assert client.get(f"/{code}").status_code == 307
    time.sleep(1.1)
    assert client.get(f"/{code}").status_code == 410


def test_delete_invalidates_cache(client: TestClient) -> None:
    code = client.post("/api/v1/links", json={"url": "https://example.com"}).json()["code"]
    client.get(f"/{code}")  # warm cache
    assert client.delete(f"/api/v1/links/{code}").status_code == 204
    assert client.get(f"/{code}").status_code == 404
    assert client.delete(f"/api/v1/links/{code}").status_code == 404


def test_rate_limit_returns_429(tmp_path: Path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "rl.db"), rate_limit_capacity=2, rate_limit_refill_per_sec=0.01
    )
    with TestClient(create_app(settings)) as c:
        statuses = [
            c.post("/api/v1/links", json={"url": "https://example.com"}).status_code
            for _ in range(3)
        ]
        assert statuses == [201, 201, 429]


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_generated_code_skips_collision_with_custom_code(client: TestClient) -> None:
    from app.codec import id_to_code

    # Squat on the code that row id 2 would generate, then force generation past it.
    squatted = id_to_code(2)
    client.post("/api/v1/links", json={"url": "https://a.com", "custom_code": squatted})
    res = client.post("/api/v1/links", json={"url": "https://b.com"})
    assert res.status_code == 201
    assert res.json()["code"] != squatted
