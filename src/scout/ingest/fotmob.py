"""FotMob adapter for team possession per match (PRD §7.1 Tier 1b, §8.4).

Possession is only needed to possession-adjust defensive volume stats (PRD §8.4). If it
is missing for a match, that match stays unadjusted and the KPI is flagged; it is never
filled in. ``soccerdata`` does the scraping; the "Top stats" team-match table is
snapshotted as CSV and parsed here with a column contract.

Each row is one team in one match, with the team's and the opponent's possession share
as fractions in [0, 1]. Matching to FPL/Understat fixtures happens in the warehouse
build (M2) on date + clubs.
"""

from __future__ import annotations

import io
import logging
import math
import re
from collections.abc import Callable, Sequence
from typing import Any

import pandas as pd

from scout.errors import DataValidationError, SourceUnavailableError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore, SourceAdapter

logger = logging.getLogger(__name__)

SOURCE = "fotmob"
LEAGUE = "ENG-Premier League"
STAT_TYPE = "Top stats"
POSSESSION = "Ball possession"
REQUIRED = frozenset({"game", "team", POSSESSION})
_SEASON_RE = re.compile(r"^(\d{4})-(\d{2})$")
_GAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s")

# soccerdata readers are untyped, so the factory returns Any.
ReaderFactory = Callable[[str], Any]


def snapshot_name(season: str) -> str:
    """Snapshot file name for one season."""
    return f"{season}_team_match_top_stats.csv"


def parse_possession(value: object) -> float | None:
    """Parse FotMob possession (``"58%"``, ``"58"``, ``58`` or ``0.58``) into a share.

    Returns:
        A fraction in [0, 1], or ``None`` if missing.

    Raises:
        DataValidationError: If the value is not a percentage.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip().rstrip("%").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise DataValidationError(f"fotmob possession {value!r} is not a number") from exc
    share = number / 100 if number > 1 else number
    if not 0.0 <= share <= 1.0:
        raise DataValidationError(f"fotmob possession {value!r} is out of range")
    return share


def _default_reader(season: str) -> Any:  # pragma: no cover - needs network + soccerdata
    try:
        import soccerdata
    except ImportError as exc:
        raise SourceUnavailableError(
            "soccerdata is not installed; run `uv sync --all-extras`"
        ) from exc
    match = _SEASON_RE.match(season)
    assert match is not None
    return soccerdata.FotMob(leagues=LEAGUE, seasons=f"{match.group(1)[2:]}{match.group(2)}")


class FotMobAdapter(SourceAdapter):
    """Fetch and parse FotMob team possession."""

    source = SOURCE

    def __init__(
        self,
        seasons: Sequence[str],
        possession_sum_tolerance: float,
        reader_factory: ReaderFactory | None = None,
    ) -> None:
        for season in seasons:
            if _SEASON_RE.match(season) is None:
                raise ValueError(f"season must look like 'YYYY-YY', got {season!r}")
        self.seasons = list(seasons)
        self.tolerance = possession_sum_tolerance
        self._reader_factory = reader_factory or _default_reader

    def fetch(self, client: PoliteClient, store: SnapshotStore) -> list[RawSnapshot]:
        """Snapshot the "Top stats" team-match table per season."""
        snapshots: list[RawSnapshot] = []
        for season in self.seasons:
            reader = self._reader_factory(season)
            client.throttle()
            frame = reader.read_team_match_stats(stat_type=STAT_TYPE)
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise SourceUnavailableError(f"fotmob returned no team stats for {season}")
            payload = frame.reset_index().to_csv(index=False).encode()
            snapshots.append(store.write(SOURCE, snapshot_name(season), payload))
        return snapshots

    def parse(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """Team-match possession rows for every configured season."""
        by_name = {s.name: s for s in snapshots}
        frames = []
        for season in self.seasons:
            snap = by_name.get(snapshot_name(season))
            if snap is None:
                raise DataValidationError(f"fotmob snapshot for {season} missing from this run")
            frames.append(self._parse_season(season, snap))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _parse_season(self, season: str, snap: RawSnapshot) -> pd.DataFrame:
        try:
            frame = pd.read_csv(io.BytesIO(snap.read_bytes()))
        except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
            raise DataValidationError(f"fotmob {snap.name} is not a valid CSV") from exc
        missing = REQUIRED - set(frame.columns)
        if missing:
            raise DataValidationError(
                f"fotmob schema changed in {snap.name}: missing {sorted(missing)}"
            )
        rows: list[dict[str, object]] = []
        for game, group in frame.groupby("game", sort=False):
            if len(group) != 2:
                raise DataValidationError(f"fotmob game {game!r} has {len(group)} team rows")
            teams = [str(t) for t in group["team"]]
            shares = [parse_possession(v) for v in group[POSSESSION]]
            first, second = shares
            if (
                first is not None
                and second is not None
                and abs(first + second - 1.0) > self.tolerance
            ):
                raise DataValidationError(
                    f"fotmob game {game!r} possession sums to {first + second:.3f}"
                )
            date_match = _GAME_DATE_RE.match(str(game))
            if date_match is None:
                raise DataValidationError(f"fotmob game key {game!r} has no leading date")
            for i in (0, 1):
                rows.append(
                    {
                        "season_id": season,
                        "game": str(game),
                        "date": pd.Timestamp(date_match.group(1)).date(),
                        "team_name": teams[i],
                        "opponent_name": teams[1 - i],
                        "possession_share": shares[i],
                        "opp_possession_share": shares[1 - i],
                        "source": SOURCE,
                        "fetched_at": snap.fetched_at,
                    }
                )
        logger.info("fotmob possession parsed", extra={"season": season, "rows": len(rows)})
        return pd.DataFrame(rows)
