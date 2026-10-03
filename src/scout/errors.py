"""Custom exceptions.

Every error raised by the engine derives from :class:`ScoutError`. The API maps each
subclass to one consistent error schema (PRD §12) using ``code`` and ``http_status``.
"""

from __future__ import annotations


class ScoutError(Exception):
    """Base class for all PL Scout Engine errors."""

    code: str = "scout_error"
    http_status: int = 500

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, object] = details or {}


class ConfigError(ScoutError):
    """A config file or environment setting is missing or invalid."""

    code = "config_error"
    http_status = 500


class DataValidationError(ScoutError):
    """Data failed schema or integrity validation (stops ``scout build``)."""

    code = "data_validation_error"
    http_status = 500


class SourceUnavailableError(ScoutError):
    """An external source is blocked, rate limited, or returned an interstitial page."""

    code = "source_unavailable"
    http_status = 503


class NotFoundError(ScoutError):
    """A requested team, player, or resource does not exist in the warehouse."""

    code = "not_found"
    http_status = 404
