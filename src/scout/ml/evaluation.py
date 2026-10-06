"""``docs/EVALUATION.md`` from one ``scout train`` run (PRD §8.11).

Every number in the report comes from the run it describes, and the header carries the
receipt: when it ran, the git commit and how fresh the player features were. A model
that was not trained shows "Not available" and the reason instead of numbers.
"""

from __future__ import annotations

from collections import Counter

from scout.ml.roles import RoleModel
from scout.ml.train import SimilarityExample, TrainResult
from scout.ml.value_model import CAVEAT, ValueModel

NOT_AVAILABLE = "Not available"
LABEL_ORDER = ("Undervalued", "Fair", "Premium")


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _dec(value: float | None, digits: int = 3) -> str:
    return NOT_AVAILABLE if value is None else f"{value:.{digits}f}"


def _pct(share: float) -> str:
    return f"{100 * share:.1f}%"


def _value_section(result: TrainResult) -> list[str]:
    lines = ["## Stats-implied market value (PRD §8.10 step 3)", "", f"> {CAVEAT}", ""]
    model: ValueModel | None = result.value
    if model is None:
        return [*lines, f"{NOT_AVAILABLE}: {result.value_skipped}.", ""]
    m, b = model.metrics["model"], model.metrics["baseline"]
    low_q, high_q = model.quantiles
    lines += [
        "Gradient-boosted trees (`HistGradientBoostingRegressor`, seed "
        f"{model.seed}) on the log of the Transfermarkt estimated market value. "
        f"Time-based split: trained on {', '.join(model.train_seasons)} "
        f"({model.n_train} player-seasons), tested on {model.test_season} "
        f"({model.n_test} player-seasons).",
        "",
        f"| Held-out season {model.test_season} | MAE (log scale) | Median absolute % error |",
        "|---|---|---|",
        f"| Model | {_dec(m['mae_log'])} | {_pct(m['median_abs_pct_error'])} |",
        "| Baseline: median by position group x age bucket | "
        f"{_dec(b['mae_log'])} | {_pct(b['median_abs_pct_error'])} |",
        "",
        "Improvement in MAE (log scale) over the baseline: "
        f"{model.metrics['improvement']['mae_log_pct']:.1f}%.",
        f"Uncertainty band (quantiles {low_q:g}-{high_q:g}): it covers "
        f"{_pct(model.band_coverage)} of held-out values (nominal {_pct(high_q - low_q)}).",
        "",
        f"Features, evaluation fit: {', '.join(model.eval_features)}.",
        f"Features, scoring fit (all seasons): {', '.join(model.features)}.",
        "",
    ]
    if result.scores.empty:
        lines += [f"This season: {NOT_AVAILABLE}: no player met the scoring rule.", ""]
    else:
        counts = Counter(str(label) for label in result.scores["value_label"])
        summary = ", ".join(f"{label} {counts.get(label, 0)}" for label in LABEL_ORDER)
        lines += [f"This season: {len(result.scores)} players scored ({summary}).", ""]
    lines += [
        "Limitations:",
        "- Training rows are past seasons of players in this season's FPL game, so players "
        "who left the league are missing (survivorship bias).",
        "- Labels are the valuation nearest each season's last kickoff within the configured "
        "window; Transfermarkt does not revalue every player on the same day.",
        "- The model reproduces how the market values output, age and club strength, "
        "including its biases.",
        "",
    ]
    return lines


def _roles_section(result: TrainResult) -> list[str]:
    lines = ["## Role archetypes (PRD §8.10 step 1)", ""]
    model: RoleModel | None = result.roles
    if model is None:
        return [*lines, f"{NOT_AVAILABLE}: {result.roles_skipped}.", ""]
    sizes = Counter(model.assignments.values())
    stability = ", ".join(_dec(a) for a in model.stability_ari) or NOT_AVAILABLE
    lines += [
        "Gaussian Mixture Model (diagonal covariance, seed "
        f"{model.seed}) on {len(model.assignments)} players' standardised KPIs "
        f"({len(model.kpis)} features); k chosen by BIC.",
        "",
        "| k | BIC |",
        "|---|---|",
        *(
            f"| {k}{' (chosen)' if k == model.k else ''} | {bic:.1f} |"
            for k, bic in sorted(model.bic.items())
        ),
        "",
        f"Silhouette score (chosen k): {_dec(model.silhouette)}.",
        f"Stability across seeds (adjusted Rand index): {stability}.",
        "",
        "| Cluster | Label | Players |",
        "|---|---|---|",
        *(
            f"| {c} | {_cell(model.labels.get(c, NOT_AVAILABLE))} | {sizes[c]} |"
            for c in sorted(sizes)
        ),
        "",
    ]
    return lines


def _similarity_line(example: SimilarityExample) -> str:
    hits = ", ".join(f"{_cell(name)} {sim:.2f}" for name, sim in example.neighbours)
    return f"- **{_cell(example.player_name)}** ({example.position_group}): {hits}"


def _similarity_section(result: TrainResult) -> list[str]:
    lines = [
        "## Similarity sanity examples (PRD §8.10 step 2)",
        "",
        "Cosine similarity of standardised, KPI-weighted vectors within a position group, "
        "starting from each group's ranked player with the most effective minutes.",
        "",
    ]
    if not result.similarity:
        return [*lines, f"{NOT_AVAILABLE}: no position group has two ranked players.", ""]
    return [*lines, *(_similarity_line(e) for e in result.similarity), ""]


def _age_section(result: TrainResult) -> list[str]:
    lines = ["## Age curves (PRD §8.10 step 4)", ""]
    curves = result.age_curves
    if curves is None:
        reason = result.age_curves_skipped or "not computed"
        return [*lines, f"{NOT_AVAILABLE}: {reason}.", ""]
    lines += [
        f"Delta method on {curves.pair_count} consecutive-season player pairs from "
        f"{', '.join(curves.seasons)} (both seasons ≥ {curves.min_minutes:.0f} minutes; ages "
        f"with fewer than {curves.min_pairs} pairs get no estimate). Typical next-season "
        "change per 90:",
        "",
        "| Age | " + " | ".join(_cell(c.label) for c in curves.curves) + " |",
        "|---|" + "---|" * len(curves.curves),
    ]
    ages = [p.age for p in curves.curves[0].points] if curves.curves else []
    for i, age in enumerate(ages):
        cells = []
        for c in curves.curves:
            point = c.points[i]
            cells.append(
                NOT_AVAILABLE if point.delta is None else f"{point.delta:+.3f} (n={point.n_pairs})"
            )
        lines.append(f"| {age} | " + " | ".join(cells) + " |")
    return [*lines, "", f"> {curves.caveat}", ""]


def render_evaluation(result: TrainResult) -> str:
    """Markdown for ``docs/EVALUATION.md``."""
    lines = [
        "# Evaluation",
        "",
        f"Generated by `uv run scout train` at {result.trained_at} "
        f"(git `{result.git_sha}`). Player features: blended season mode, as of "
        f"{result.features_as_of or NOT_AVAILABLE}. Numbers describe that run only; "
        "regenerate after every `scout build`.",
        "",
        *_value_section(result),
        *_roles_section(result),
        *_similarity_section(result),
        *_age_section(result),
    ]
    return "\n".join(lines).rstrip("\n") + "\n"
