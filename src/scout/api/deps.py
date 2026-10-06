"""Shared API state: settings, config, the warehouse engine and the hot-endpoint cache.

The API only reads the warehouse (PRD §14). Expensive results (diagnosis, shortlists,
fact sheets, search indexes) are kept in the hand-written LRU cache (``dsa.lru_cache``)
under a key that starts with the **warehouse version**, so a new ``scout build`` or
``scout train`` (which rewrite the database) can never serve stale results.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy import Engine, inspect

from scout.config import AppConfig, Settings
from scout.db.build import last_build_path
from scout.db.session import make_engine
from scout.dsa.lru_cache import LRUCache
from scout.engines.diagnosis import SeasonContext, season_context
from scout.errors import NotFoundError, WarehouseNotReadyError

NOT_BUILT = "Run `scout ingest` and `scout build` (or `scout demo`) to create the warehouse."


@dataclass
class ApiState:
    """Process-wide API state (one per app)."""

    settings: Settings
    config: AppConfig
    engine: Engine
    cache: LRUCache[tuple[Hashable, ...], object]
    lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def create(cls, settings: Settings, config: AppConfig) -> ApiState:
        """State with a lazily connecting engine and an empty cache."""
        return cls(
            settings=settings,
            config=config,
            engine=make_engine(settings.database_url),
            cache=LRUCache(config.settings.api.cache_capacity),
        )

    def _sqlite_file(self) -> Path | None:
        url = self.settings.database_url
        if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
            return Path(url.removeprefix("sqlite:///"))
        return None

    def last_build(self) -> dict[str, object] | None:
        """The summary ``scout build`` wrote, if any."""
        path = last_build_path(self.settings)
        if not path.exists():
            return None
        data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def warehouse_version(self) -> str | None:
        """When the warehouse was last built (``None`` before the first build)."""
        build = self.last_build()
        built_at = build.get("built_at") if build else None
        return str(built_at) if built_at is not None else None

    def cache_token(self) -> str:
        """Changes whenever the warehouse is rebuilt or retrained."""
        db = self._sqlite_file()
        mtime = db.stat().st_mtime_ns if db is not None and db.exists() else 0
        return f"{self.warehouse_version()}|{mtime}"

    def cached[T](self, key: tuple[Hashable, ...], compute: Callable[[], T]) -> T:
        """Return the cached value for ``key`` under the current warehouse version."""
        full = (self.cache_token(), *key)
        with self.lock:
            hit = self.cache.get(full)
        if hit is not None:
            return cast(T, hit)
        value = compute()
        with self.lock:
            self.cache.put(full, value)
        return value

    def season(self) -> SeasonContext:
        """Current season and clubs.

        Raises:
            WarehouseNotReadyError: If there is no built warehouse yet.
        """
        db = self._sqlite_file()
        if db is not None and not db.exists():
            raise WarehouseNotReadyError(NOT_BUILT)

        def load() -> SeasonContext:
            if "dim_season" not in inspect(self.engine).get_table_names():
                raise WarehouseNotReadyError(NOT_BUILT)
            try:
                return season_context(self.engine)
            except NotFoundError as exc:
                raise WarehouseNotReadyError(NOT_BUILT) from exc

        return self.cached(("season",), load)


def get_state(request: Request) -> ApiState:
    """FastAPI dependency: the app's :class:`ApiState`."""
    return cast(ApiState, request.app.state.scout)


State = Annotated[ApiState, Depends(get_state)]
