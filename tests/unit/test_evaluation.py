"""docs/EVALUATION.md rendering (PRD §8.11): every number comes from the run."""

import pandas as pd

from scout.ml.evaluation import render_evaluation
from scout.ml.train import SimilarityExample
from scout.ml.value_model import CAVEAT, train_value_model
from tests.unit.test_train import _result, _roles
from tests.unit.test_value_model import CFG, GROUPS, synthetic_seasons


def test_report_carries_metrics_and_receipts() -> None:
    value = train_value_model(synthetic_seasons(n=60), CFG, GROUPS, seed=5)
    roles = _roles()
    result = _result(roles=roles, value=value)
    result.scores = pd.DataFrame({"value_label": ["Undervalued", "Fair", "Fair"]})
    result.similarity = [SimilarityExample(4, "Four", "ST", (("Two", 0.91), ("O|ne", 0.5)))]
    text = render_evaluation(result)
    assert text.startswith("# Evaluation\n") and text.endswith("\n")
    assert "git `abc1234`" in text and "as of 2026-09-01 00:00:00" in text
    assert CAVEAT in text
    model, baseline = value.metrics["model"], value.metrics["baseline"]
    assert f"| Model | {model['mae_log']:.3f} |" in text
    assert f"| {baseline['mae_log']:.3f} |" in text
    assert f"tested on {value.test_season} ({value.n_test} player-seasons)" in text
    assert "3 players scored (Undervalued 1, Fair 2, Premium 0)" in text
    assert f"| {roles.k} (chosen) |" in text
    assert all(label in text for label in roles.labels.values())
    assert "- **Four** (ST): Two 0.91, O\\|ne 0.50" in text  # table-safe names
    assert "Not available" not in text


def test_skipped_models_say_why() -> None:
    text = render_evaluation(_result())
    assert "Not available: too few seasons." in text
    assert "Not available: too few players." in text
    assert "Not available: no position group has two ranked players." in text
    assert "| Model |" not in text and "(chosen)" not in text
