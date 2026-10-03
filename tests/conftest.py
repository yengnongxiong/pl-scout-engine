"""Shared test setup: block all outbound network access (CLAUDE.md "Testing and CI")."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver"}


class NetworkBlockedError(RuntimeError):
    """Raised when a test tries to reach the network."""


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and (host in _LOCAL_HOSTS or self.family == socket.AF_UNIX):
            return real_connect(self, address)
        raise NetworkBlockedError(f"network access blocked in tests: {address!r}")

    def blocked_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host in _LOCAL_HOSTS:
            return real_getaddrinfo(host, *args, **kwargs)
        raise NetworkBlockedError(f"DNS lookup blocked in tests: {host!r}")

    real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", blocked_getaddrinfo)
    yield
