"""SQLAlchemy 2.0 models for the gold-layer star schema (PRD §11).

Fact tables are stored long by source: one row per (entity, match, source). FPL and
Understat describe the same player-match with different columns, and keeping them as
separate rows means every stored number carries exactly one ``source`` and
``fetched_at`` (CLAUDE.md rule 3). The feature layer selects each KPI's column from the
row whose source matches ``config/kpis.yaml``.

Only portable column types are used so the same schema runs on SQLite and Postgres.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names keep Alembic migrations portable across backends.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with a shared naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class DimSeason(Base):
    """A season, e.g. ``"2026-27"`` (derived from FPL, never hardcoded)."""

    __tablename__ = "dim_season"

    season_id: Mapped[str] = mapped_column(String(7), primary_key=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)


class DimTeam(Base):
    """A club, with its identifiers in each source."""

    __tablename__ = "dim_team"

    team_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    short_name: Mapped[str | None] = mapped_column(String(10))
    aliases: Mapped[str | None] = mapped_column(Text, doc="JSON list of alternative names")
    fpl_code: Mapped[int | None] = mapped_column(Integer, unique=True)
    understat_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    tm_id: Mapped[str | None] = mapped_column(String(20), unique=True)


class DimPlayer(Base):
    """A player resolved across sources (FPL ``code`` is the stable FPL key)."""

    __tablename__ = "dim_player"

    player_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(150))
    birth_date: Mapped[date | None] = mapped_column(Date)
    fpl_code: Mapped[int | None] = mapped_column(Integer, unique=True)
    understat_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    tm_id: Mapped[str | None] = mapped_column(String(20), unique=True)
    detailed_position: Mapped[str | None] = mapped_column(String(50))
    position_group: Mapped[str | None] = mapped_column(String(3))


class DimMatch(Base):
    """A Premier League match with its identifiers in each source."""

    __tablename__ = "dim_match"

    match_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_id: Mapped[str] = mapped_column(ForeignKey("dim_season.season_id"))
    gameweek: Mapped[int | None] = mapped_column(Integer)
    kickoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("dim_team.team_id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("dim_team.team_id"))
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    fpl_fixture_code: Mapped[int | None] = mapped_column(Integer, unique=True)
    understat_game_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    fotmob_game: Mapped[str | None] = mapped_column(String(200), unique=True)


class FactPlayerMatch(Base):
    """Player x match x source counting stats (raw, not per 90)."""

    __tablename__ = "fact_player_match"
    __table_args__ = (UniqueConstraint("player_id", "match_id", "source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("dim_player.player_id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("dim_match.match_id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("dim_team.team_id"))
    minutes: Mapped[int | None] = mapped_column(Integer)
    started: Mapped[bool | None] = mapped_column(Boolean)
    goals: Mapped[int | None] = mapped_column(Integer)
    assists: Mapped[int | None] = mapped_column(Integer)
    xg: Mapped[float | None] = mapped_column(Float)
    npxg: Mapped[float | None] = mapped_column(Float)
    xa: Mapped[float | None] = mapped_column(Float)
    shots: Mapped[int | None] = mapped_column(Integer)
    key_passes: Mapped[int | None] = mapped_column(Integer)
    xg_chain: Mapped[float | None] = mapped_column(Float)
    xg_buildup: Mapped[float | None] = mapped_column(Float)
    tackles: Mapped[int | None] = mapped_column(Integer)
    recoveries: Mapped[int | None] = mapped_column(Integer)
    cbi: Mapped[int | None] = mapped_column(Integer)
    def_contribution: Mapped[int | None] = mapped_column(Integer)
    xgc_on_pitch: Mapped[float | None] = mapped_column(Float)
    yellow_cards: Mapped[int | None] = mapped_column(Integer)
    red_cards: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(30))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FactTeamMatch(Base):
    """Team x match x source stats (xG, PPDA, deep, possession, set pieces)."""

    __tablename__ = "fact_team_match"
    __table_args__ = (UniqueConstraint("team_id", "match_id", "source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("dim_team.team_id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("dim_match.match_id"), index=True)
    xg: Mapped[float | None] = mapped_column(Float)
    xga: Mapped[float | None] = mapped_column(Float)
    npxg: Mapped[float | None] = mapped_column(Float)
    npxga: Mapped[float | None] = mapped_column(Float)
    ppda: Mapped[float | None] = mapped_column(Float)
    ppda_allowed: Mapped[float | None] = mapped_column(Float)
    deep: Mapped[int | None] = mapped_column(Integer)
    deep_allowed: Mapped[int | None] = mapped_column(Integer)
    possession: Mapped[float | None] = mapped_column(Float, doc="Share in [0, 1]")
    set_piece_xg: Mapped[float | None] = mapped_column(Float)
    set_piece_xga: Mapped[float | None] = mapped_column(Float)
    open_play_xga: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(30))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FactMarketValue(Base):
    """A Transfermarkt estimated market value with Transfermarkt's own as-of date."""

    __tablename__ = "fact_market_value"
    __table_args__ = (UniqueConstraint("player_id", "source", "tm_last_updated"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("dim_player.player_id"), index=True)
    value_eur: Mapped[int | None] = mapped_column(BigInteger)
    tm_last_updated: Mapped[date | None] = mapped_column(Date)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text, doc="Required for overrides")
    source: Mapped[str] = mapped_column(String(30), doc="transfermarkt / snapshot / override")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FactPlayerStatus(Base):
    """Availability and contract snapshot for a player."""

    __tablename__ = "fact_player_status"
    __table_args__ = (UniqueConstraint("player_id", "source", "fetched_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("dim_player.player_id"), index=True)
    fpl_status: Mapped[str | None] = mapped_column(String(2))
    news: Mapped[str | None] = mapped_column(Text)
    chance_of_playing: Mapped[int | None] = mapped_column(Integer)
    contract_expiry: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(30))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceSnapshot(Base):
    """One ingested raw snapshot, for freshness and ``scout doctor`` (PRD §14)."""

    __tablename__ = "source_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(200))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rows: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), doc="ok / invalid / failed")
    error: Mapped[str | None] = mapped_column(Text)


class EntityMapReview(Base):
    """A source record that entity resolution could not map confidently."""

    __tablename__ = "entity_map_review"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(150))
    team: Mapped[str | None] = mapped_column(String(100))
    best_candidate: Mapped[int | None] = mapped_column(ForeignKey("dim_player.player_id"))
    score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlayerSeasonFeature(Base):
    """Materialised per-player KPI values (PRD §11 ``player_season_features``).

    One row per player x season mode (``blended`` / ``current``) x KPI: the raw current
    per-90, the blended value, the shrunk value used for ranking, its percentile among
    position-group peers with ``n_peers``, minutes, proxy and possession-adjustment
    flags, and the newest source timestamp behind it.
    """

    __tablename__ = "player_season_features"
    __table_args__ = (UniqueConstraint("player_id", "season_mode", "kpi"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("dim_player.player_id"), index=True)
    season_mode: Mapped[str] = mapped_column(String(10))
    position_group: Mapped[str] = mapped_column(String(3))
    kpi: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(30))
    raw_p90: Mapped[float | None] = mapped_column(Float)
    value: Mapped[float | None] = mapped_column(Float)
    shrunk: Mapped[float | None] = mapped_column(Float)
    percentile: Mapped[float | None] = mapped_column(Float)
    n_peers: Mapped[int] = mapped_column(Integer)
    minutes: Mapped[float] = mapped_column(Float)
    effective_minutes: Mapped[float] = mapped_column(Float)
    used_previous_season: Mapped[bool] = mapped_column(Boolean)
    is_proxy: Mapped[bool] = mapped_column(Boolean)
    padj_status: Mapped[str | None] = mapped_column(String(12))
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlayerRole(Base):
    """A player's role archetype from the last ``scout train`` run (PRD §8.10 step 1).

    Written by ``scout train`` so the API reads archetypes from the warehouse like every
    other number; ``trained_at`` and ``git_sha`` are the receipt of the model behind it.
    """

    __tablename__ = "player_role"
    __table_args__ = (UniqueConstraint("player_id", "season_mode"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("dim_player.player_id"), index=True)
    season_mode: Mapped[str] = mapped_column(String(10))
    cluster: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(200))
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    git_sha: Mapped[str] = mapped_column(String(40))


class PlayerValueScore(Base):
    """Stats-implied value next to the Transfermarkt estimated market value (PRD §8.10).

    One row per player x season from the last ``scout train`` run. The Transfermarkt value
    keeps its own receipt (source, Transfermarkt as-of date, stale flag); the model's band
    and label carry ``trained_at`` and ``git_sha``.
    """

    __tablename__ = "player_value_score"
    __table_args__ = (UniqueConstraint("player_id", "season_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("dim_player.player_id"), index=True)
    season_id: Mapped[str] = mapped_column(ForeignKey("dim_season.season_id"))
    value_eur: Mapped[int] = mapped_column(BigInteger)
    value_source: Mapped[str] = mapped_column(String(30))
    tm_last_updated: Mapped[date] = mapped_column(Date)
    value_is_stale: Mapped[bool] = mapped_column(Boolean)
    implied_value_eur: Mapped[float] = mapped_column(Float)
    band_low_eur: Mapped[float] = mapped_column(Float)
    band_high_eur: Mapped[float] = mapped_column(Float)
    value_label: Mapped[str] = mapped_column(String(12))
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    git_sha: Mapped[str] = mapped_column(String(40))
