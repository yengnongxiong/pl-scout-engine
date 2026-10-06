"""Template scouting reports (PRD §9 step 2): Jinja2 + seeded phrase banks.

The renderer only ever reads the fact sheet, and formats numbers through
``reports.format`` so the grounding validator can check every one of them. Phrase choice
is seeded by player, club and the configured ML seed, so the same inputs always give the
same report while different players don't all read alike.
"""

from __future__ import annotations

import random
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml
from jinja2 import Environment, PackageLoader, StrictUndefined

from scout.config import AppConfig
from scout.engines.fit import weighted_percentile
from scout.reports import format as fmt
from scout.reports.facts import FactSheet, percentile_band

FPL_STATUS = {
    "a": "available",
    "d": "doubtful",
    "i": "injured",
    "s": "suspended",
    "u": "unavailable (left the club)",
    "n": "not available",
}


@lru_cache(maxsize=1)
def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("scout.reports", "templates"),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,  # plain text, never HTML
    )
    env.filters.update(
        per90=fmt.per90,
        ordinal=fmt.ordinal,
        score=fmt.score,
        points=fmt.points,
        whole=fmt.whole,
        peer_noun=fmt.peer_noun,
        minutes=fmt.minutes,
        age=fmt.age,
        eur_m=fmt.eur_m,
        cosine=fmt.cosine,
        iso_date=fmt.iso_date,
    )
    return env


@lru_cache(maxsize=1)
def phrase_bank() -> dict[str, Any]:
    """The phrase banks (``templates/phrases.yaml``)."""
    text = resources.files("scout.reports").joinpath("templates/phrases.yaml").read_text("utf-8")
    bank: dict[str, Any] = yaml.safe_load(text)
    return bank


def _pick(rng: random.Random, options: list[str], **variables: object) -> str:
    return _environment().from_string(rng.choice(options)).render(**variables)


def _status(sheet: FactSheet) -> str:
    if sheet.fpl_status is None:
        return fmt.NOT_AVAILABLE
    words = FPL_STATUS.get(sheet.fpl_status, sheet.fpl_status)
    if sheet.chance_of_playing is not None:
        words += f", {fmt.whole(sheet.chance_of_playing)}% chance of playing"
    return f"{words} (FPL, as of {fmt.iso_date(sheet.status_as_of)})"


def _market_value(sheet: FactSheet) -> str:
    mv = sheet.market_value
    if mv is None:
        return fmt.NOT_AVAILABLE
    stale = ", stale snapshot" if mv.is_stale else ""
    as_of = mv.tm_last_updated.isoformat()
    return f"{fmt.eur_m(mv.value_eur)} (Transfermarkt as of {as_of}{stale})"


def _verdict(sheet: FactSheet, rng: random.Random, config: AppConfig) -> str:
    bank = phrase_bank()
    fit = sheet.fit
    if fit is None:
        weights = {k.kpi: k.weight for k in sheet.kpis}
        pcts = {k.kpi: k.percentile for k in sheet.kpis}
        band = percentile_band(weighted_percentile(pcts, weights), config.settings.reports.bands)
        return _pick(
            rng, bank["overall"][band or "unknown"],
            name=sheet.player_name, group=sheet.position_group,
        )  # fmt: skip
    variables = {
        "name": sheet.player_name,
        "club": fit.team_name,
        "group": fit.position_group,
        "inc": fit.incumbent.player_name if fit.incumbent else "",
    }
    if fit.same_club:
        key = "same_club"
    elif (
        fit.gate == "upgrade"
        and fit.fit_score is not None
        and fit.fit_score >= config.settings.reports.strong_fit_score
    ):
        key = "strong_fit"
    else:
        key = fit.gate
    return _pick(rng, bank["verdict"][key], **variables)


def report_seed(sheet: FactSheet, config: AppConfig) -> str:
    """Seed for phrase choice: player, club and the configured seed (stable across runs)."""
    club = sheet.fit.team_id if sheet.fit else "none"
    return f"{sheet.player_id}-{club}-{config.settings.ml.seed}"


def render_template_report(sheet: FactSheet, config: AppConfig) -> str:
    """Plain-text scouting report from ``sheet`` (copy-ready, PRD US-06)."""
    rng = random.Random(report_seed(sheet, config))
    bank = phrase_bank()
    strengths = [sheet.kpi(k) for k in sheet.strengths]
    concerns = [sheet.kpi(k) for k in sheet.concerns]
    band_phrase = {
        k.kpi: rng.choice(bank["band"][k.band]) for k in [*strengths, *concerns] if k.band
    }
    return (
        _environment()
        .get_template("report.txt.j2")
        .render(
            s=sheet,
            fit=sheet.fit,
            market_value=_market_value(sheet),
            status=_status(sheet),
            verdict=_verdict(sheet, rng, config),
            strengths=strengths,
            concerns=concerns,
            strengths_intro=_pick(rng, bank["strengths_intro"], name=sheet.player_name),
            concerns_intro=_pick(rng, bank["concerns_intro"], name=sheet.player_name),
            band_phrase=band_phrase,
        )
    )
