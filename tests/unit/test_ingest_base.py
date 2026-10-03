from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from scout.config import PROJECT_ROOT, IngestConfig, load_config
from scout.dsa.token_bucket import TokenBucket
from scout.errors import SourceUnavailableError
from scout.ingest.base import PoliteClient, SnapshotStore

BODY = b'{"events": [], "teams": [], "elements": [], "padding": "' + b"x" * 80 + b'"}'


def ingest_config(**overrides: object) -> IngestConfig:
    base = load_config(PROJECT_ROOT / "config").settings.ingest
    data = base.model_dump()
    data.update(backoff_initial_seconds=0.0, backoff_max_seconds=0.0)
    data.update(overrides)
    return IngestConfig.model_validate(data)


def fast_bucket() -> TokenBucket:
    return TokenBucket(1e9, 1e9)


def client_for(
    handler: Callable[[httpx.Request], httpx.Response], max_requests: int | None = None
) -> PoliteClient:
    return PoliteClient(
        "fpl",
        ingest_config(),
        transport=httpx.MockTransport(handler),
        bucket=fast_bucket(),
        max_requests=max_requests,
    )


def test_sends_descriptive_user_agent() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, content=BODY)

    with client_for(handler) as client:
        assert client.get("https://example.test/api") == BODY
    assert seen and "pl-scout-engine" in seen[0]


def test_retries_transient_errors_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, content=b"busy")
        return httpx.Response(200, content=BODY)

    with client_for(handler) as client:
        assert client.get("https://example.test/api") == BODY
        assert client.requests_made == 3


def test_gives_up_after_max_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with client_for(handler) as client, pytest.raises(SourceUnavailableError, match="giving up"):
        client.get("https://example.test/api")
    assert client.requests_made == ingest_config().max_retries + 1


def test_forbidden_is_not_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b"Host not in allowlist")

    with client_for(handler) as client, pytest.raises(SourceUnavailableError, match="HTTP 403"):
        client.get("https://example.test/api")
    assert client.requests_made == 1


@pytest.mark.parametrize(
    "content",
    [b"", b"<html><title>Just a moment...</title>" + b" " * 100 + b"</html>"],
)
def test_empty_or_interstitial_pages_fail(content: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, content=content)

    with client_for(handler) as client, pytest.raises(SourceUnavailableError):
        client.get("https://example.test/api")


def test_request_budget_enforced() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=BODY)

    with client_for(handler, max_requests=2) as client:
        client.get("https://example.test/a")
        client.get("https://example.test/b")
        with pytest.raises(SourceUnavailableError, match="budget"):
            client.get("https://example.test/c")


def test_unknown_source_without_rate_limit_rejected() -> None:
    with pytest.raises(SourceUnavailableError, match="no rate limit"):
        PoliteClient("nowhere", ingest_config())


def test_snapshot_store_round_trip_and_ttl(tmp_path: Path) -> None:
    now = [datetime(2026, 10, 3, 12, 0, tzinfo=UTC)]
    store = SnapshotStore(tmp_path, clock=lambda: now[0])
    first = store.write("fpl", "bootstrap-static.json", b'{"a": 1}')
    now[0] += timedelta(hours=1)
    second = store.write("fpl", "bootstrap-static.json", b'{"a": 2}')
    assert first.path != second.path
    assert first.checksum != second.checksum

    latest = store.latest("fpl", "bootstrap-static.json", max_age=timedelta(hours=12))
    assert latest is not None
    assert latest.read_json() == {"a": 2}
    assert latest.fetched_at == second.fetched_at
    assert latest.checksum == second.checksum

    now[0] += timedelta(hours=13)
    assert store.latest("fpl", "bootstrap-static.json", max_age=timedelta(hours=12)) is None
    assert store.latest("fpl", "bootstrap-static.json") is not None
    assert store.latest("fpl", "missing.json") is None
    assert store.latest("understat", "x.json") is None


def test_latest_all_returns_newest_copy_of_each_file(tmp_path: Path) -> None:
    now = [datetime(2026, 10, 1, tzinfo=UTC)]
    store = SnapshotStore(tmp_path, clock=lambda: now[0])
    store.write("fpl", "a.json", b"1")
    now[0] += timedelta(seconds=1)
    store.write("fpl", "b.json", b"2")
    now[0] += timedelta(seconds=1)
    store.write("fpl", "a.json", b"3")
    latest = {s.name: s.read_bytes() for s in store.latest_all("fpl")}
    assert latest == {"a.json": b"3", "b.json": b"2"}
    assert store.latest_all("understat") == []
