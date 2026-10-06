"""Scouting reports: fact sheet → template → grounding (PRD §9, milestone M6)."""

import os
from datetime import date
from pathlib import Path

import httpx
import pytest

from scout.config import PROJECT_ROOT, Settings, load_config
from scout.reports import format as fmt
from scout.reports.facts import (
    Caveat,
    ComparableFact,
    FactSheet,
    FitFact,
    ImpliedValueFact,
    IncumbentFact,
    KpiFact,
    MarketValueFact,
    NeedKpiFact,
    Receipt,
    RoleFact,
    allowed_numbers,
    percentile_band,
    strengths_and_concerns,
)
from scout.reports.generate import generate_report, template_vocabulary
from scout.reports.grounding import check_numbers, validate
from scout.reports.render import render_template_report

CONFIG = load_config(PROJECT_ROOT / "config")
GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "reports"
AS_OF = "2026-09-28 10:00:00+00:00"


def _kpi(kpi: str, weight: float, value: float, pct: float, **kw: object) -> KpiFact:
    definition = CONFIG.kpis.kpis[kpi]
    return KpiFact(
        kpi=kpi,
        label=definition.label,
        weight=weight,
        is_proxy=definition.is_proxy,
        proxy_for=definition.proxy_for,
        value=value,
        raw_p90=value,
        percentile=pct,
        band=percentile_band(pct, CONFIG.settings.reports.bands),
        n_peers=kw.get("n_peers", 48),  # type: ignore[arg-type]
        source=definition.source,
        as_of=AS_OF,
        padj_status=None,
    )


def synthetic_sheet(*, with_fit: bool = True) -> FactSheet:
    """A made-up striker; every value is synthetic."""
    kpis = [
        _kpi("npxg_p90", 0.40, 0.52, 93.0),
        _kpi("shots_p90", 0.20, 3.4, 81.0),
        _kpi("npxg_per_shot", 0.15, 0.15, 62.0),
        _kpi("xg_chain_p90", 0.15, 0.61, 55.0),
        _kpi("xa_p90", 0.10, 0.06, 12.0),
        _kpi("goals_minus_xg_p90", 0.0, 0.08, 70.0),
    ]
    strengths, concerns = strengths_and_concerns(kpis, 3)
    fit = FitFact(
        team_id=2,
        team_name="Synthetic Rovers",
        benchmark="top6",
        position_group="ST",
        same_club=False,
        fit_score=78.4,
        components={
            "need_fill": 88.0,
            "role_quality": 74.6,
            "reliability": 91.2,
            "style_fit": 63.5,
            "age_profile": 100.0,
        },
        weights_used={
            "need_fill": 0.4,
            "role_quality": 0.25,
            "reliability": 0.15,
            "style_fit": 0.1,
            "age_profile": 0.1,
        },
        gate="upgrade",
        gate_min_delta=15.0,
        need_fill=88.0,
        incumbent=IncumbentFact(
            player_id=7, player_name="Ivo Placeholder", minutes=610.0, need_fill=41.0
        ),
        need_kpis=[
            NeedKpiFact(
                kpi="npxg_p90",
                label=CONFIG.kpis.kpis["npxg_p90"].label,
                is_proxy=False,
                gap=31.0,
                candidate_percentile=93.0,
                incumbent_percentile=35.0,
                delta=58.0,
            )
        ],
    )
    return FactSheet(
        player_id=11,
        player_name="Sam Synthetic",
        team_id=1,
        team_name="Fixture Town",
        position_group="ST",
        birth_date=date(1999, 4, 2),
        age=27.5,
        as_of=date(2026, 10, 1),
        season_mode="blended",
        current_season="2026-27",
        previous_season="2025-26",
        minutes=540.0,
        effective_minutes=1540.0,
        fpl_status="a",
        chance_of_playing=None,
        status_as_of=AS_OF,
        contract_expiry=date(2028, 6, 30),
        market_value=MarketValueFact(
            value_eur=38_000_000,
            tm_last_updated=date(2026, 9, 15),
            source="transfermarkt",
            is_stale=False,
        ),
        kpis=kpis,
        strengths=strengths,
        concerns=concerns,
        role=RoleFact(label="high Non-penalty xG, high Shots", trained_at=AS_OF, git_sha="abc1234"),
        comparables=[
            ComparableFact(
                player_id=21, player_name="Kit Example", team_name="Mock City", similarity=0.91
            ),
            ComparableFact(player_id=22, player_name="Lou Sample", team_name=None, similarity=0.84),
        ],
        implied_value=ImpliedValueFact(
            implied_value_eur=52_400_000,
            band_low_eur=41_000_000,
            band_high_eur=66_000_000,
            label="Undervalued",
            trained_at=AS_OF,
            git_sha="abc1234",
            caveat="Stats-implied value, not a fee prediction.",
        ),
        fit=fit if with_fit else None,
        caveats=[
            Caveat(
                kind="proxy_metric",
                text="Proxy metrics (stand-ins for data not freely available): "
                "Possession involvement (xGChain per 90).",
            )
        ],
        sources=[
            Receipt(source="fpl", as_of=AS_OF),
            Receipt(source="transfermarkt", as_of="2026-09-15"),
            Receipt(source="understat", as_of=AS_OF),
        ],
    )


def _golden(name: str, text: str) -> None:
    path = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8"), f"golden file {name} differs"


def test_percentile_bands_follow_config() -> None:
    bands = CONFIG.settings.reports.bands
    assert [percentile_band(p, bands) for p in (95, 90, 89.9, 75, 50, 49, 25, 24.9)] == [
        "elite", "elite", "strong", "strong", "above_average", "below_average",
        "below_average", "weak",
    ]  # fmt: skip
    assert percentile_band(None, bands) is None
    assert percentile_band(float("nan"), bands) is None


def test_strengths_and_concerns_skip_zero_weight_kpis() -> None:
    sheet = synthetic_sheet()
    # goals_minus_xg rates p70 but has weight 0: shown in the table, never listed.
    assert sheet.strengths == ["npxg_p90", "shots_p90"]
    assert sheet.concerns == ["xa_p90"]


def test_template_report_matches_golden_file() -> None:
    _golden("synthetic_report_fit.txt", render_template_report(synthetic_sheet(), CONFIG))
    _golden(
        "synthetic_report_profile.txt",
        render_template_report(synthetic_sheet(with_fit=False), CONFIG),
    )


def test_template_report_is_deterministic_and_grounded() -> None:
    sheet = synthetic_sheet()
    text = render_template_report(sheet, CONFIG)
    assert text == render_template_report(sheet, CONFIG)
    result = validate(text, sheet, reference=template_vocabulary())
    assert result.ok, result.violations
    for needle in ("€38.0m (Transfermarkt as of 2026-09-15)", "93rd percentile among 48 ST",
                   "Ivo Placeholder 35th (+58)", "2026-27 blended with 2025-26"):  # fmt: skip
        assert needle in text


@pytest.mark.parametrize(
    ("injected", "reason"),
    [
        ("He averages 4.7 shots per 90.", "number '4.7'"),
        ("Valued at €61.5m elsewhere.", "money '€61.5m'"),
        ("Signed on 2025-01-31.", "date '2025-01-31'"),
        ("Top scorer in 2019-20.", "season '2019-20'"),
        ("Compared with Erling Haaland.", "name 'Erling'"),
    ],
)
def test_validator_rejects_injected_facts(injected: str, reason: str) -> None:
    sheet = synthetic_sheet()
    text = render_template_report(sheet, CONFIG) + injected + "\n"
    result = validate(text, sheet, reference=template_vocabulary())
    assert not result.ok
    assert any(reason in v for v in result.violations), result.violations


def test_number_matching_respects_shown_rounding_and_sign() -> None:
    allowed = {0.52, 93.0, -12.0, 38.0}
    assert check_numbers("0.52 and 0.5 and 93rd and 38", allowed, 1e-6) == []
    assert check_numbers("trails by 12 (-12)", allowed, 1e-6) == []
    assert check_numbers("+12", allowed, 1e-6) == ["number '+12' is not in the fact sheet"]
    assert check_numbers("0.53", allowed, 1e-6) == ["number '0.53' is not in the fact sheet"]
    assert check_numbers("1,234", {1234.0}, 1e-6) == []


def test_allowed_numbers_include_display_scales() -> None:
    numbers = allowed_numbers(synthetic_sheet())
    assert {38.0, 52.4, 40.0, 91.0, 2026.0} <= numbers  # €m, weight %, similarity %


def test_report_formats() -> None:
    assert (fmt.per90(0.523), fmt.per90(3.44), fmt.per90(None)) == ("0.52", "3.4", "Not available")
    assert [fmt.ordinal(x) for x in (1, 2, 3, 4, 11, 12, 13, 21, 22, 93, 100)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "93rd", "100th",
    ]  # fmt: skip
    assert (fmt.points(12.4), fmt.points(-3.0), fmt.whole(1234.4)) == ("+12", "-3", "1,234")
    assert (fmt.eur_m(38_000_000), fmt.age(27.46), fmt.cosine(0.914)) == ("€38.0m", "27.5", "0.91")
    assert (fmt.minutes(1540), fmt.share(0.43), fmt.score(78.44)) == (
        "1,540 minutes",
        "43%",
        "78.4",
    )
    assert fmt.iso_date("2026-09-28 10:00:00") == "2026-09-28"
    assert fmt.iso_date(date(2026, 9, 1)) == "2026-09-01"
    for f in (fmt.ordinal, fmt.score, fmt.points, fmt.whole, fmt.minutes, fmt.age, fmt.eur_m,
              fmt.share, fmt.cosine):  # fmt: skip
        assert f(None) == "Not available"
    assert fmt.iso_date(None) == "Not available"


def _settings(engine: str, model: str | None = "llama3.1:8b") -> Settings:
    return Settings(report_engine=engine, ollama_model=model)  # type: ignore[call-arg]


def _ollama(answer: object, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "localhost" and request.url.path == "/api/generate"
        return httpx.Response(status, json={"response": answer})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_template_engine_is_the_default() -> None:
    report = generate_report(synthetic_sheet(), _settings("template"), CONFIG)
    assert (report.engine, report.requested_engine, report.fallback_reason) == (
        "template",
        "template",
        None,
    )


def test_grounded_llm_rewrite_is_used() -> None:
    sheet = synthetic_sheet()
    template = render_template_report(sheet, CONFIG)
    rewritten = template.replace("STRENGTHS", "STRENGTHS (summary)")
    report = generate_report(sheet, _settings("ollama"), CONFIG, client=_ollama(rewritten))
    assert report.engine == "ollama" and report.text.startswith("SCOUTING REPORT")


def test_llm_rewrite_with_a_fake_number_falls_back_to_the_template() -> None:
    sheet = synthetic_sheet()
    template = render_template_report(sheet, CONFIG)
    hallucinated = template + "He scored 47 goals last season.\n"
    report = generate_report(sheet, _settings("ollama"), CONFIG, client=_ollama(hallucinated))
    assert report.engine == "template" and report.text == template
    assert report.fallback_reason == "LLM output failed grounding"
    assert any("'47'" in v for v in report.violations)


@pytest.mark.parametrize(
    ("client", "model", "reason"),
    [
        (None, None, "SCOUT_OLLAMA_MODEL is not set"),
        ("error", "m", "local LLM unavailable"),
        ("empty", "m", "local LLM unavailable"),
    ],
)
def test_llm_failures_fall_back(client: str | None, model: str | None, reason: str) -> None:
    http = {"error": _ollama("x", status=500), "empty": _ollama("   ")}.get(client or "")
    report = generate_report(synthetic_sheet(), _settings("ollama", model), CONFIG, client=http)
    assert report.engine == "template" and report.requested_engine == "ollama"
    assert report.fallback_reason is not None and reason in report.fallback_reason


def test_ollama_unreachable_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    report = generate_report(synthetic_sheet(), _settings("ollama"), CONFIG, client=client)
    assert report.fallback_reason == "local LLM unavailable"
