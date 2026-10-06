"""Liveness endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from scout import __version__
from scout.api.deps import State
from scout.api.schemas import HealthResponse

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
def health(state: State) -> HealthResponse:
    """Report liveness and when the warehouse was last built."""
    return HealthResponse(
        status="ok", version=__version__, warehouse_version=state.warehouse_version()
    )
