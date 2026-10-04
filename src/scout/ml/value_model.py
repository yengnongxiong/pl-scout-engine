"""Stats-implied market value: the "Moneyball" model (PRD §8.10 step 3, US-11).

Gradient-boosted trees (``HistGradientBoostingRegressor``) predict the log of a player's
Transfermarkt estimated market value from age (and age squared), position group, minutes
share, per-90 output and club strength. Every input is scale-free (no raw minutes), so a
part-season can be scored on the same footing as the full seasons the model learned from.
Logs because values span three orders of magnitude and errors are proportional (a €2m miss
matters on a €5m player, not on €80m).

Evaluation uses a **time-based split**: train on earlier seasons, test on the latest
completed season, so the model never sees the future it is scored on. It is compared with
a **baseline**: the median log value of the training rows in the same position group and
age bucket. Reported: MAE on the log scale and median absolute % error, for both.

Two quantile models (lower / upper, config) give an uncertainty band. A player whose
Transfermarkt value sits below the band is **Undervalued** by the stats, above it
**Premium**, inside it **Fair**. Caveat shown wherever this is displayed: the model learns
the market's own biases; it is a stats-implied value, not a fee prediction.

Missing features (e.g. FPL expected goals before 2022-23) are passed as NaN and handled by
the trees' native missing-value branches; nothing is filled in. A column with fewer than two
distinct known values in the training rows carries no signal and is left out of that fit
(the fitted model records the columns it used). Every fit is seeded.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from scout.config import ValueModelConfig

BandLabel = Literal["Undervalued", "Fair", "Premium"]
GROUP_FEATURE = "position_group"
MIN_SEASONS = 2  # a time-based split needs a training season and a test season
MIN_DISTINCT = 2  # a feature needs two known values to split on


def feature_names(per90_stats: Sequence[str]) -> list[str]:
    """Model columns, in order (the position group is ordinal-coded as categorical)."""
    return ["age", "age_sq", "minutes_share", "team_ppg",
            *(f"{s}_p90" for s in per90_stats), GROUP_FEATURE]  # fmt: skip


def _float(value: object) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return math.nan
    return float(str(value))


def feature_matrix(
    frame: pd.DataFrame, per90_stats: Sequence[str], groups: Sequence[str]
) -> npt.NDArray[np.float64]:
    """Rows of model inputs; unknown values are NaN (never 0)."""
    codes = {g: float(i) for i, g in enumerate(groups)}
    rows: list[list[float]] = []
    for rec in frame.to_dict(orient="records"):
        age = _float(rec.get("age"))
        row = [age, age * age, _float(rec.get("minutes_share")), _float(rec.get("team_ppg"))]
        row += [_float(rec.get(f"{s}_p90")) for s in per90_stats]
        row.append(codes.get(str(rec.get(GROUP_FEATURE)), math.nan))
        rows.append(row)
    width = len(feature_names(per90_stats))
    return np.array(rows, dtype=np.float64).reshape(len(rows), width)


def informative_columns(x: npt.NDArray[np.float64]) -> tuple[int, ...]:
    """Indices of columns with at least two distinct known values."""
    keep: list[int] = []
    for j in range(x.shape[1]):
        col = x[:, j]
        if np.unique(col[~np.isnan(col)]).size >= MIN_DISTINCT:
            keep.append(j)
    return tuple(keep)


def age_bucket(age: float | None, edges: Sequence[float]) -> int | None:
    """Index of the first edge the age is <= to (len(edges) for older); None if unknown."""
    if age is None or math.isnan(age):
        return None
    return next((i for i, edge in enumerate(edges) if age <= edge), len(edges))


@dataclass
class Baseline:
    """Median log value by position group x age bucket, with fallbacks."""

    edges: tuple[float, ...]
    cells: dict[tuple[str, int], float]
    groups: dict[str, float]
    overall: float

    @classmethod
    def fit(cls, frame: pd.DataFrame, edges: Sequence[float]) -> Baseline:
        """Medians from training rows (``position_group``, ``age``, ``log_value``)."""
        cells: dict[tuple[str, int], list[float]] = {}
        groups: dict[str, list[float]] = {}
        values: list[float] = []
        for rec in frame.to_dict(orient="records"):
            y = float(rec["log_value"])
            values.append(y)
            group = str(rec[GROUP_FEATURE])
            groups.setdefault(group, []).append(y)
            bucket = age_bucket(_float(rec.get("age")), edges)
            if bucket is not None:
                cells.setdefault((group, bucket), []).append(y)
        return cls(
            edges=tuple(edges),
            cells={k: statistics.median(v) for k, v in cells.items()},
            groups={k: statistics.median(v) for k, v in groups.items()},
            overall=statistics.median(values),
        )

    def predict(self, frame: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Cell median, else the group median, else the overall median."""
        out: list[float] = []
        for rec in frame.to_dict(orient="records"):
            group = str(rec[GROUP_FEATURE])
            bucket = age_bucket(_float(rec.get("age")), self.edges)
            cell = self.cells.get((group, bucket)) if bucket is not None else None
            out.append(cell if cell is not None else self.groups.get(group, self.overall))
        return np.array(out, dtype=np.float64)


def error_metrics(
    y_true: npt.NDArray[np.float64], y_pred: npt.NDArray[np.float64]
) -> dict[str, float]:
    """MAE on the log scale and median absolute % error on the euro scale."""
    return {
        "mae_log": float(np.mean(np.abs(y_pred - y_true))),
        "median_abs_pct_error": float(np.median(np.abs(np.exp(y_pred - y_true) - 1.0))),
    }


@dataclass
class ValueModel:
    """Fitted point and quantile models, the baseline and held-out evaluation."""

    per90_stats: tuple[str, ...]
    groups: tuple[str, ...]
    columns: tuple[int, ...]
    eval_columns: tuple[int, ...]
    quantiles: tuple[float, float]
    seed: int
    train_seasons: tuple[str, ...]
    test_season: str
    n_train: int
    n_test: int
    metrics: dict[str, dict[str, float]]
    band_coverage: float
    point: Any = field(repr=False)
    low: Any = field(repr=False)
    high: Any = field(repr=False)
    baseline: Baseline = field(repr=False)

    @property
    def features(self) -> list[str]:
        """Input columns of the scoring model (fitted on every season)."""
        names = feature_names(self.per90_stats)
        return [names[j] for j in self.columns]

    @property
    def eval_features(self) -> list[str]:
        """Input columns of the evaluation model (fitted on the training seasons only)."""
        names = feature_names(self.per90_stats)
        return [names[j] for j in self.eval_columns]

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Stats-implied value and band (euros), quantiles kept in order per row."""
        x = feature_matrix(frame, self.per90_stats, self.groups)[:, list(self.columns)]
        stacked = np.sort(
            np.column_stack([self.low.predict(x), self.point.predict(x), self.high.predict(x)]),
            axis=1,
        )
        return pd.DataFrame(
            {
                "implied_value_eur": np.exp(stacked[:, 1]),
                "band_low_eur": np.exp(stacked[:, 0]),
                "band_high_eur": np.exp(stacked[:, 2]),
            },
            index=frame.index,
        )


def _regressor(
    cfg: ValueModelConfig, seed: int, quantile: float | None, categorical: list[bool]
) -> Any:
    loss = "squared_error" if quantile is None else "quantile"
    return HistGradientBoostingRegressor(
        loss=loss,
        quantile=quantile,
        max_iter=cfg.max_iter,
        learning_rate=cfg.learning_rate,
        categorical_features=categorical,
        random_state=seed,
    )


def _fit_all(
    x: npt.NDArray[np.float64], y: npt.NDArray[np.float64], cfg: ValueModelConfig, seed: int
) -> tuple[tuple[int, ...], Any, Any, Any]:
    """Fit point, low and high models on the informative columns of ``x``."""
    columns = informative_columns(x)
    if not columns:
        raise ValueError("no feature has two distinct known values; cannot fit")
    names = feature_names(cfg.per90_stats)
    categorical = [names[j] == GROUP_FEATURE for j in columns]
    low_q, high_q = cfg.quantiles
    models = tuple(_regressor(cfg, seed, q, categorical) for q in (None, low_q, high_q))
    for model in models:
        model.fit(x[:, list(columns)], y)
    point, low, high = models
    return columns, point, low, high


def band_label(value_eur: float, low_eur: float, high_eur: float) -> BandLabel:
    """Where the Transfermarkt value sits against the stats-implied band."""
    if value_eur < low_eur:
        return "Undervalued"
    if value_eur > high_eur:
        return "Premium"
    return "Fair"


def train_value_model(
    frame: pd.DataFrame, cfg: ValueModelConfig, groups: Sequence[str], seed: int
) -> ValueModel:
    """Evaluate on the latest season held out, then refit on every season for scoring.

    Raises:
        ValueError: If fewer than two seasons are labelled (no time-based split possible).
    """
    seasons = sorted({str(s) for s in frame["season_id"]})
    if len(seasons) < MIN_SEASONS:
        raise ValueError(f"need labelled rows from at least 2 seasons, got {seasons}")
    test_season, train_seasons = seasons[-1], seasons[:-1]
    train = frame[frame["season_id"].isin(train_seasons)]
    test = frame[frame["season_id"] == test_season]
    y_train = train["log_value"].to_numpy(dtype=np.float64)
    y_test = test["log_value"].to_numpy(dtype=np.float64)
    x_train = feature_matrix(train, cfg.per90_stats, groups)
    x_test = feature_matrix(test, cfg.per90_stats, groups)
    eval_columns, point, low, high = _fit_all(x_train, y_train, cfg, seed)
    x_test = x_test[:, list(eval_columns)]
    baseline = Baseline.fit(train, cfg.age_bucket_edges)
    model_m = error_metrics(y_test, point.predict(x_test))
    base_m = error_metrics(y_test, baseline.predict(test))
    lows, highs = low.predict(x_test), high.predict(x_test)
    coverage = float(
        np.mean((y_test >= np.minimum(lows, highs)) & (y_test <= np.maximum(lows, highs)))
    )
    metrics = {
        "model": model_m,
        "baseline": base_m,
        "improvement": {
            "mae_log_pct": 100.0 * (1.0 - model_m["mae_log"] / base_m["mae_log"])
            if base_m["mae_log"] > 0
            else 0.0
        },
    }
    x_all = feature_matrix(frame, cfg.per90_stats, groups)
    y_all = frame["log_value"].to_numpy(dtype=np.float64)
    columns, point, low, high = _fit_all(x_all, y_all, cfg, seed)
    return ValueModel(
        per90_stats=tuple(cfg.per90_stats),
        groups=tuple(groups),
        columns=columns,
        eval_columns=eval_columns,
        quantiles=cfg.quantiles,
        seed=seed,
        train_seasons=tuple(train_seasons),
        test_season=test_season,
        n_train=len(train),
        n_test=len(test),
        metrics=metrics,
        band_coverage=coverage,
        point=point,
        low=low,
        high=high,
        baseline=Baseline.fit(frame, cfg.age_bucket_edges),
    )


def metadata(model: ValueModel, extra: Mapping[str, object] | None = None) -> dict[str, object]:
    """JSON-safe description of a fitted model (saved next to the artefact)."""
    return {
        "model": "HistGradientBoostingRegressor(log Transfermarkt estimated market value)",
        "features": model.features,
        "eval_features": model.eval_features,
        "groups": list(model.groups),
        "quantiles": list(model.quantiles),
        "seed": model.seed,
        "train_seasons": list(model.train_seasons),
        "test_season": model.test_season,
        "n_train": model.n_train,
        "n_test": model.n_test,
        "metrics": model.metrics,
        "band_coverage": model.band_coverage,
        **(extra or {}),
    }
