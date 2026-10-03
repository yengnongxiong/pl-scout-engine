import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.db.models import Base, DimMatch, DimSeason, DimTeam
from scout.db.queries import standings
from scout.db.session import make_engine, make_session_factory
from scout.engines.benchmark import benchmark_clubs
from scout.errors import ConfigError

SIZES = load_config(PROJECT_ROOT / "config").settings.diagnosis.benchmark_sizes
SEASON = "2025-26"
# (home, away, home goals, away goals); team ids 1-5.
RESULTS = [
    (1, 2, 2, 0), (2, 1, 1, 1), (3, 1, 0, 3), (1, 4, 1, 0), (2, 3, 2, 2),
    (4, 2, 0, 1), (3, 4, 1, 0), (4, 3, 2, 2), (5, 1, 0, 0), (2, 5, 3, 0),
    (5, 3, None, None),  # not played yet: ignored
]  # fmt: skip


def pandas_twin(results: list[tuple[int, int, int | None, int | None]]) -> pd.DataFrame:
    rows = []
    for h, a, hg, ag in results:
        if hg is None or ag is None:
            continue
        rows.append((h, hg, ag))
        rows.append((a, ag, hg))
    df = pd.DataFrame(rows, columns=["team_id", "gf", "ga"])
    df["pts"] = (df["gf"] > df["ga"]) * 3 + (df["gf"] == df["ga"]) * 1
    t = df.groupby("team_id").agg(
        played=("gf", "size"), points=("pts", "sum"), goals_for=("gf", "sum"),
        goals_against=("ga", "sum"),
    ).reset_index()  # fmt: skip
    t["goal_difference"] = t["goals_for"] - t["goals_against"]
    key = list(zip(-t["points"], -t["goal_difference"], -t["goals_for"], strict=True))
    order = sorted(set(key))
    t["position"] = [1 + sum(key.count(k) for k in order[: order.index(v)]) for v in key]
    return t.sort_values(["position", "team_id"]).reset_index(drop=True)


@pytest.fixture
def table() -> pd.DataFrame:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        s.add(DimSeason(season_id=SEASON, is_current=False))
        s.add_all([DimTeam(team_id=i, name=f"Club {i}") for i in range(1, 6)])
        s.flush()  # parents first: matches reference seasons and teams
        s.add_all(
            [
                DimMatch(season_id=SEASON, home_team_id=h, away_team_id=a, home_score=hg,
                         away_score=ag)
                for h, a, hg, ag in RESULTS
            ]
        )  # fmt: skip
        s.commit()
    return standings(engine, SEASON)


def test_table_matches_pandas_twin(table: pd.DataFrame) -> None:
    twin = pandas_twin(RESULTS)
    cols = ["team_id", "played", "points", "goals_for", "goals_against", "goal_difference",
            "position"]  # fmt: skip
    assert table[cols].astype(int).values.tolist() == twin[cols].astype(int).values.tolist()


def test_hand_calculated_table(table: pd.DataFrame) -> None:
    by_team = table.set_index("team_id")
    # Club 1: W2-0, D1-1, W3-0, W1-0, D0-0 -> 11 pts, 7 scored, 1 conceded, GD +6.
    assert (by_team.loc[1, "points"], by_team.loc[1, "goal_difference"]) == (11, 6)
    assert by_team.loc[1, "position"] == 1
    assert by_team.loc[5, "played"] == 2  # unplayed fixture ignored


def test_benchmark_top_n_excludes_club(table: pd.DataFrame) -> None:
    assert benchmark_clubs(table, "top4", club_id=1, sizes=SIZES) == [2, 3, 4]
    assert len(benchmark_clubs(table, "top6", club_id=99, sizes=SIZES)) == 5  # whole table


def test_benchmark_league_and_custom(table: pd.DataFrame) -> None:
    assert benchmark_clubs(table, "league", club_id=2, sizes=SIZES, league_clubs=[1, 2, 3]) == [
        1,
        3,
    ]
    assert benchmark_clubs(table, "custom", club_id=2, sizes=SIZES, custom=[2, 5]) == [5]


def test_benchmark_errors(table: pd.DataFrame) -> None:
    with pytest.raises(ConfigError, match="no clubs"):
        benchmark_clubs(table, "custom", club_id=2, sizes=SIZES, custom=[2])
    with pytest.raises(ConfigError, match="no completed season"):
        benchmark_clubs(table.iloc[0:0], "top6", club_id=2, sizes=SIZES)
