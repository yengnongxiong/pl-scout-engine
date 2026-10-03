"""Pydantic response models shared by every router (PRD §12)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """Machine-readable error details."""

    code: str = Field(description="Stable error code, e.g. 'not_found'.")
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """The single error schema returned by every endpoint."""

    error: ErrorBody


class HealthResponse(BaseModel):
    """Liveness plus warehouse version."""

    status: Literal["ok"]
    version: str = Field(description="Engine version.")
    warehouse_version: str | None = Field(
        description="Warehouse build identifier; null until `scout build` has run."
    )
