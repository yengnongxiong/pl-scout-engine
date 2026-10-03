"""FastAPI application factory.

The API is read-only and reads the warehouse only (PRD §12, §14). Every
:class:`~scout.errors.ScoutError` is mapped to the single :class:`ErrorResponse` schema.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from scout import __version__
from scout.api.routers import health
from scout.api.schemas import ErrorBody, ErrorResponse
from scout.errors import ScoutError

# Vite dev server origin (CLAUDE.md "Known gotchas"; PRD §12).
ALLOWED_ORIGINS = ["http://localhost:5173"]


async def _scout_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ScoutError)
    body = ErrorResponse(error=ErrorBody(code=exc.code, message=exc.message, details=exc.details))
    return JSONResponse(status_code=exc.http_status, content=body.model_dump())


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title="PL Scout Engine API",
        version=__version__,
        description="Read-only API over the local warehouse. No number without a receipt.",
        responses={500: {"model": ErrorResponse}},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ScoutError, _scout_error_handler)
    app.include_router(health.router)
    return app


app = create_app()
