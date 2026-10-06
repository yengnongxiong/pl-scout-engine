"""One error schema for every failure (PRD §12): engine errors, validation, unknown routes."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from scout.api.schemas import ErrorBody, ErrorResponse
from scout.errors import ScoutError

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Unknown club, player or need."},
    422: {"model": ErrorResponse, "description": "Invalid request parameters."},
    503: {"model": ErrorResponse, "description": "The warehouse has not been built yet."},
}


def _body(code: str, message: str, details: dict[str, object] | None = None) -> dict[str, Any]:
    return ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details or {})
    ).model_dump(mode="json")


async def scout_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Map a :class:`ScoutError` to its HTTP status and the error schema."""
    assert isinstance(exc, ScoutError)
    return JSONResponse(
        status_code=exc.http_status, content=_body(exc.code, exc.message, exc.details)
    )


async def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's parameter validation errors, in the same schema."""
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": jsonable_encoder(e.get("loc", ())), "msg": str(e.get("msg")), "type": e.get("type")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_body("invalid_request", "Invalid request parameters.", {"errors": errors}),
    )


async def http_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Routing errors (unknown path, wrong method), in the same schema."""
    assert isinstance(exc, StarletteHTTPException)
    code = "not_found" if exc.status_code == 404 else "http_error"
    return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)))
