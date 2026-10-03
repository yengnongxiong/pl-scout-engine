"""Shared ingestion machinery: snapshot store, polite HTTP client, and the adapter ABC.

Every source sits behind one :class:`SourceAdapter` (PRD §10 "Adapter pattern"):
``fetch()`` writes raw, timestamped snapshots to ``data/raw`` (bronze, always replayable)
and ``parse()`` turns them into a validated DataFrame. When a source changes or dies, only
its adapter changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from scout.config import IngestConfig
from scout.dsa.token_bucket import TokenBucket
from scout.errors import SourceUnavailableError

logger = logging.getLogger(__name__)

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RawSnapshot:
    """One raw payload written to the bronze store."""

    source: str
    name: str
    path: Path
    fetched_at: datetime
    checksum: str

    def read_bytes(self) -> bytes:
        """Return the raw payload."""
        return self.path.read_bytes()

    def read_json(self) -> object:
        """Parse the payload as JSON."""
        return json.loads(self.read_bytes())


class SnapshotStore:
    """Timestamped raw snapshots under ``<root>/<source>/<timestamp>/<name>``.

    The newest snapshot younger than the TTL doubles as the HTTP cache, so repeated runs
    don't re-hit sources (CLAUDE.md rule 11).
    """

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self.root = root
        self._clock = clock or (lambda: datetime.now(UTC))

    def write(self, source: str, name: str, payload: bytes) -> RawSnapshot:
        """Persist ``payload`` and return its snapshot record."""
        fetched_at = self._clock()
        directory = self.root / source / fetched_at.strftime(_TIMESTAMP_FORMAT)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(payload)
        checksum = hashlib.sha256(payload).hexdigest()
        logger.info(
            "snapshot written", extra={"source": source, "file": name, "bytes": len(payload)}
        )
        return RawSnapshot(source, name, path, fetched_at, checksum)

    def latest(
        self, source: str, name: str, max_age: timedelta | None = None
    ) -> RawSnapshot | None:
        """Return the newest snapshot of ``name``, optionally only if younger than ``max_age``."""
        source_dir = self.root / source
        if not source_dir.is_dir():
            return None
        for directory in sorted(source_dir.iterdir(), reverse=True):
            path = directory / name
            if not path.is_file():
                continue
            fetched_at = datetime.strptime(directory.name, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
            if max_age is not None and self._clock() - fetched_at > max_age:
                return None
            payload = path.read_bytes()
            return RawSnapshot(source, name, path, fetched_at, hashlib.sha256(payload).hexdigest())
        return None

    def latest_all(self, source: str) -> list[RawSnapshot]:
        """Newest snapshot of every file name for ``source`` (the latest complete run).

        Each write lands in its own timestamped directory, so a source's latest run is
        the newest copy of each distinct file name.
        """
        source_dir = self.root / source
        if not source_dir.is_dir():
            return []
        names = sorted({p.name for d in source_dir.iterdir() if d.is_dir() for p in d.iterdir()})
        out = [self.latest(source, name) for name in names]
        return [snap for snap in out if snap is not None]


class _RetryableError(Exception):
    """Internal marker for transient failures that tenacity should retry."""


class PoliteClient:
    """HTTP client with a descriptive User-Agent, rate limiting, retries and block detection.

    Args:
        source: Source name (used for rate limit lookup and error messages).
        config: Ingestion settings.
        transport: Optional httpx transport (tests inject ``httpx.MockTransport``).
        bucket: Optional token bucket; defaults to the configured rate for ``source``.
        max_requests: Optional hard cap on requests for this client (per-run budget).
    """

    def __init__(
        self,
        source: str,
        config: IngestConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        bucket: TokenBucket | None = None,
        max_requests: int | None = None,
    ) -> None:
        self.source = source
        self.config = config
        if bucket is None:
            rate = next((r for s, r in config.rate_limits.items() if s == source), None)
            if rate is None:
                raise SourceUnavailableError(f"no rate limit configured for source {source!r}")
            bucket = TokenBucket(rate)
        self._bucket = bucket
        self._max_requests = max_requests
        self.requests_made = 0
        self._client = httpx.Client(
            headers={"User-Agent": config.user_agent},
            timeout=config.timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _check_payload(self, url: str, response: httpx.Response) -> None:
        body = response.content
        if len(body) < self.config.min_body_bytes:
            raise SourceUnavailableError(
                f"{self.source}: empty or truncated response from {url}",
                details={"status": response.status_code, "bytes": len(body)},
            )
        text = response.text.casefold()
        for marker in self.config.interstitial_markers:
            if marker.casefold() in text:
                raise SourceUnavailableError(
                    f"{self.source}: interstitial/anti-bot page from {url}",
                    details={"status": response.status_code, "marker": marker},
                )

    def throttle(self) -> None:
        """Spend one request from the budget and wait for the rate limiter.

        Used before calls made by third-party fetchers (e.g. ``soccerdata``) that do their
        own HTTP, so they still respect this source's rate limit and per-run budget.
        """
        if self._max_requests is not None and self.requests_made >= self._max_requests:
            raise SourceUnavailableError(
                f"{self.source}: request budget of {self._max_requests} exhausted"
            )
        self._bucket.acquire()
        self.requests_made += 1

    def _attempt(self, url: str, params: dict[str, str] | None) -> httpx.Response:
        self.throttle()
        try:
            response = self._client.get(url, params=params)
        except httpx.TransportError as exc:
            raise _RetryableError(str(exc)) from exc
        if response.status_code in _RETRYABLE_STATUS:
            raise _RetryableError(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            # 403/404 etc. are not transient: blocked host, removed endpoint. Fail loudly once.
            raise SourceUnavailableError(
                f"{self.source}: HTTP {response.status_code} from {url}",
                details={"status": response.status_code},
            )
        self._check_payload(url, response)
        return response

    def get(self, url: str, params: dict[str, str] | None = None) -> bytes:
        """GET ``url`` politely and return the validated body.

        Raises:
            SourceUnavailableError: On a non-transient HTTP error, an interstitial page,
                an exhausted request budget, or when retries are exhausted.
        """
        retrying = Retrying(
            stop=stop_after_attempt(self.config.max_retries + 1),
            wait=wait_exponential(
                multiplier=self.config.backoff_initial_seconds,
                max=self.config.backoff_max_seconds,
            ),
            retry=retry_if_exception_type(_RetryableError),
            reraise=False,
        )
        try:
            response = retrying(self._attempt, url, params)
        except RetryError as exc:
            cause = exc.last_attempt.exception()
            raise SourceUnavailableError(
                f"{self.source}: giving up on {url} after {self.config.max_retries + 1} attempts",
                details={"last_error": str(cause)},
            ) from cause
        return response.content


class SourceAdapter(ABC):
    """Interface every data source implements (PRD §10)."""

    #: Short source id, matching ``config/settings.yaml`` ``ingest.rate_limits`` keys.
    source: str

    @abstractmethod
    def fetch(self, client: PoliteClient, store: SnapshotStore) -> Sequence[RawSnapshot]:
        """Download raw payloads and write them to the snapshot store."""

    @abstractmethod
    def parse(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """Parse raw snapshots into a validated DataFrame.

        Every returned row carries ``source`` and ``fetched_at`` (CLAUDE.md rule 3).

        Raises:
            DataValidationError: If the payload no longer matches the expected schema.
        """
