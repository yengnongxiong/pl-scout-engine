"""Liveness endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from scout import __version__
from scout.api.schemas import HealthResponse

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report liveness and the warehouse version."""
    # The warehouse arrives in M2; until then there is no build to report.
    return HealthResponse(status="ok", version=__version__, warehouse_version=None)
