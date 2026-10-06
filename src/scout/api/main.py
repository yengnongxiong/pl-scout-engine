"""FastAPI application factory.

The API is read-only and reads the warehouse only (PRD §12, §14). Every error, from the
engine or from request validation, uses the single :class:`ErrorResponse` schema.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from scout import __version__
from scout.api.deps import ApiState
from scout.api.errors import http_error_handler, scout_error_handler, validation_error_handler
from scout.api.routers import compare, health, meta, players, teams
from scout.api.schemas import ErrorResponse
from scout.config import AppConfig, Settings, get_config, get_settings
from scout.errors import ScoutError

# Vite dev server origin (CLAUDE.md "Known gotchas"; PRD §12).
ALLOWED_ORIGINS = ["http://localhost:5173"]


def create_app(settings: Settings | None = None, config: AppConfig | None = None) -> FastAPI:
    """Build the FastAPI application over the warehouse named in ``settings``."""
    app = FastAPI(
        title="PL Scout Engine API",
        version=__version__,
        description="Read-only API over the local warehouse. No number without a receipt.",
        responses={500: {"model": ErrorResponse}},
    )
    app.state.scout = ApiState.create(settings or get_settings(), config or get_config())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ScoutError, scout_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    for module in (health, meta, teams, players, compare):
        app.include_router(module.router)
    return app


app = create_app()
