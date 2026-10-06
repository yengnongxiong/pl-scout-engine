"""Scouting report generation: template by default, optional local LLM, always grounded.

PRD §9: the fact sheet is rendered with the template engine; with ``REPORT_ENGINE=ollama``
the template report is rewritten by a local model and the rewrite is shown only if the
grounding validator accepts it. Otherwise the template report is shown and the reason is
recorded (and logged), so 100% of shown reports are grounded (PRD §15).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from importlib import resources
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

from scout.config import AppConfig, Settings
from scout.reports.facts import FactSheet
from scout.reports.grounding import validate
from scout.reports.llm import rewrite
from scout.reports.render import render_template_report

logger = logging.getLogger(__name__)

TEMPLATE_FILES = ("templates/report.txt.j2", "templates/phrases.yaml")


class Report(BaseModel):
    """A scouting report with how it was produced."""

    model_config = ConfigDict(frozen=True)

    text: str
    engine: Literal["template", "ollama"]
    requested_engine: Literal["template", "ollama"]
    fallback_reason: str | None = None
    violations: list[str] = []


@lru_cache(maxsize=1)
def template_vocabulary() -> str:
    """The static wording of the templates and phrase banks (allowed in any report)."""
    root = resources.files("scout.reports")
    return "\n".join(root.joinpath(name).read_text("utf-8") for name in TEMPLATE_FILES)


def generate_report(
    sheet: FactSheet,
    settings: Settings,
    config: AppConfig,
    *,
    client: httpx.Client | None = None,
) -> Report:
    """Render, optionally rewrite, and validate a report for ``sheet``."""
    tolerance = config.settings.reports.grounding_tolerance
    template = render_template_report(sheet, config)
    checked = validate(template, sheet, reference=template_vocabulary(), tolerance=tolerance)
    if not checked.ok:
        # A template that is not grounded is a bug: refuse to show it rather than guess.
        raise ValueError(f"template report is not grounded: {checked.violations}")
    requested = settings.report_engine
    if requested == "template":
        return Report(text=template, engine="template", requested_engine=requested)
    if not settings.ollama_model:
        reason = "REPORT_ENGINE=ollama but SCOUT_OLLAMA_MODEL is not set"
        logger.warning("report fallback", extra={"reason": reason})
        return Report(
            text=template, engine="template", requested_engine=requested, fallback_reason=reason
        )
    rewritten = rewrite(
        template,
        model=settings.ollama_model,
        cfg=config.settings.reports.ollama,
        seed=config.settings.ml.seed,
        client=client,
    )
    if rewritten is None:
        reason = "local LLM unavailable"
        return Report(
            text=template, engine="template", requested_engine=requested, fallback_reason=reason
        )
    result = validate(rewritten, sheet, reference=template, tolerance=tolerance)
    if not result.ok:
        logger.warning(
            "LLM report discarded by grounding validator",
            extra={"player_id": sheet.player_id, "violations": result.violations},
        )
        return Report(
            text=template,
            engine="template",
            requested_engine=requested,
            fallback_reason="LLM output failed grounding",
            violations=result.violations,
        )
    return Report(text=rewritten, engine="ollama", requested_engine=requested)
