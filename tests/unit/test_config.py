import shutil
from pathlib import Path

import pytest
import yaml

from scout.config import PROJECT_ROOT, load_config
from scout.errors import ConfigError

CONFIG_DIR = PROJECT_ROOT / "config"


@pytest.fixture
def config_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, dest)
    return dest


def _edit(path: Path, mutate: object) -> None:
    data = yaml.safe_load(path.read_text())
    assert callable(mutate)
    mutate(data)
    path.write_text(yaml.safe_dump(data))


def test_committed_config_is_valid() -> None:
    cfg = load_config(CONFIG_DIR)
    assert set(cfg.kpis.position_groups) == {"CB", "FB", "DM", "CM", "AM", "W", "ST"}
    assert cfg.fit_weights.components["need_fill"] == pytest.approx(0.40)
    assert cfg.settings.methodology.blend_lambda == pytest.approx(0.5)


def test_every_proxy_kpi_explains_itself() -> None:
    cfg = load_config(CONFIG_DIR)
    proxies = {k for k, v in cfg.kpis.kpis.items() if v.is_proxy}
    assert {"def_activity_padj_p90", "xg_buildup_p90", "xg_chain_p90"} <= proxies
    assert all(cfg.kpis.kpis[k].proxy_for for k in proxies)


def test_weights_not_summing_to_one_rejected(config_copy: Path) -> None:
    _edit(
        config_copy / "kpis.yaml",
        lambda d: d["position_groups"]["CB"]["weights"].update(cards_p90=0.5),
    )
    with pytest.raises(ConfigError, match="CB: weights sum"):
        load_config(config_copy)


def test_unknown_kpi_id_rejected(config_copy: Path) -> None:
    _edit(
        config_copy / "kpis.yaml",
        lambda d: d["position_groups"]["ST"]["weights"].update(made_up=0.0),
    )
    with pytest.raises(ConfigError, match="unknown KPI ids"):
        load_config(config_copy)


def test_proxy_without_explanation_rejected(config_copy: Path) -> None:
    _edit(config_copy / "kpis.yaml", lambda d: d["kpis"]["xg_chain_p90"].pop("proxy_for"))
    with pytest.raises(ConfigError, match="proxy_for"):
        load_config(config_copy)


def test_fit_weights_must_sum_to_one(config_copy: Path) -> None:
    _edit(config_copy / "fit_weights.yaml", lambda d: d["components"].update(style_fit=0.5))
    with pytest.raises(ConfigError, match="FitScore weights sum"):
        load_config(config_copy)


def test_reliability_config_validated(config_copy: Path) -> None:
    _edit(
        config_copy / "fit_weights.yaml",
        lambda d: d["reliability"]["status_availability"].update(a=1.5),
    )
    with pytest.raises(ConfigError, match="within"):
        load_config(config_copy)
    _edit(
        config_copy / "fit_weights.yaml",
        lambda d: d["reliability"].update(
            volume_weight=0, availability_weight=0, status_availability={"a": 1.0}
        ),
    )
    with pytest.raises(ConfigError, match="both be zero"):
        load_config(config_copy)


def test_inverted_possession_clip_rejected(config_copy: Path) -> None:
    _edit(
        config_copy / "settings.yaml",
        lambda d: d["methodology"].update(possession_multiplier_min=2.0),
    )
    with pytest.raises(ConfigError, match="possession_multiplier_min"):
        load_config(config_copy)


def test_duplicate_alias_across_clubs_rejected(config_copy: Path) -> None:
    _edit(
        config_copy / "team_aliases.yaml",
        lambda d: d["aliases"]["Chelsea"].append("Spurs"),
    )
    with pytest.raises(ConfigError, match="Spurs"):
        load_config(config_copy)


def test_unknown_field_rejected(config_copy: Path) -> None:
    _edit(config_copy / "settings.yaml", lambda d: d["ml"].update(sneaky=1))
    with pytest.raises(ConfigError):
        load_config(config_copy)


def test_missing_file_rejected(config_copy: Path) -> None:
    (config_copy / "positions.yaml").unlink()
    with pytest.raises(ConfigError, match="missing config file"):
        load_config(config_copy)


def test_invalid_yaml_rejected(config_copy: Path) -> None:
    (config_copy / "positions.yaml").write_text("groups: [CB\n")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(config_copy)
