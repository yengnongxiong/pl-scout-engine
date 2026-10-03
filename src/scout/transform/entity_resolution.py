"""Cross-source player entity resolution (CLAUDE.md "Known gotchas"; PRD §15).

FPL players are the anchors (FPL ``code`` is stable). Understat and Transfermarkt records
are matched to them in four steps:

1. **Block by club.** Candidates are only FPL players at the same club(s), after mapping
   each source's club name to an FPL club with the alias table. This keeps comparisons
   small and stops two different "Danny Wards" from merging.
2. **Score names.** Names are normalised (accents, case, punctuation) and compared with
   the hand-written Levenshtein similarity, both as written and with tokens sorted, so
   "Son Heung-min" matches "Heung-Min Son".
3. **Decide.** Accept the best candidate only if it clears ``accept_score`` and beats the
   runner-up by ``min_margin``; a date-of-birth mismatch (when both are known) vetoes it.
   Manual overrides in ``data/overrides/player_overrides.csv`` win outright.
4. **Merge.** Accepted links are unioned with union-find; if two records from one source
   claim the same FPL player, the higher score wins and the other goes to review.

Anything not accepted is written to ``entity_map_review`` instead of being guessed.
Coverage is measured as the share of FPL minutes whose player is linked to each source
(PRD §15 target ≥ 98%).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from scout.config import EntityResolutionConfig
from scout.dsa.levenshtein import similarity
from scout.dsa.union_find import UnionFind
from scout.errors import DataValidationError
from scout.transform.clean import normalise_person_name, sorted_tokens

logger = logging.getLogger(__name__)

MATCH_SOURCES = ("understat", "transfermarkt")


@dataclass(frozen=True)
class AnchorPlayer:
    """An FPL player: the anchor every other source is matched to."""

    fpl_code: int
    names: tuple[str, ...]
    team_code: int
    minutes: float = 0.0
    birth_date: date | None = None


@dataclass(frozen=True)
class SourceRecord:
    """A player record from a non-FPL source, with its clubs mapped to FPL team codes."""

    source: str
    source_id: str
    name: str
    team_codes: frozenset[int]
    team_label: str | None = None
    birth_date: date | None = None


@dataclass(frozen=True)
class Link:
    """An accepted match between a source record and an FPL anchor."""

    source: str
    source_id: str
    fpl_code: int
    score: float
    method: str


@dataclass(frozen=True)
class ReviewItem:
    """A record that could not be matched confidently."""

    source: str
    source_id: str
    name: str
    team: str | None
    best_candidate: int | None
    score: float | None
    reason: str


@dataclass
class Resolution:
    """Result of resolving every source against the FPL anchors."""

    links: list[Link] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    coverage: dict[str, float] = field(default_factory=dict)

    def mapping_frame(self, anchors: Sequence[AnchorPlayer]) -> pd.DataFrame:
        """One row per FPL player with the linked id in each source (null if unlinked)."""
        by_code: dict[int, dict[str, object]] = {
            a.fpl_code: {"fpl_code": a.fpl_code, "canonical_name": a.names[0]}
            | {f"{s}_id": None for s in MATCH_SOURCES}
            for a in anchors
        }
        for link in self.links:
            by_code[link.fpl_code][f"{link.source}_id"] = link.source_id
        return pd.DataFrame(list(by_code.values()))

    def coverage_report(self, target: float) -> str:
        """Human-readable minutes coverage per source against the PRD target."""
        lines: list[str] = []
        for source, share in sorted(self.coverage.items()):
            flag = "ok" if share >= target else "BELOW TARGET"
            lines.append(
                f"{source}: {share:.1%} of FPL minutes mapped ({flag}, target {target:.0%})"
            )
        lines.append(f"unresolved records for review: {len(self.review)}")
        return "\n".join(lines)


def map_clubs(
    source_names: Iterable[str],
    fpl_teams: Mapping[int, str],
    aliases: Mapping[str, Sequence[str]],
) -> dict[str, int | None]:
    """Map club names as a source spells them to FPL team codes (``None`` if unknown)."""
    spelling_to_canonical: dict[str, str] = {}
    for canonical, alts in aliases.items():
        for spelling in (canonical, *alts):
            spelling_to_canonical[normalise_person_name(spelling)] = canonical
    canonical_to_code: dict[str, int] = {}
    for code, name in fpl_teams.items():
        key = normalise_person_name(name)
        canonical_to_code[spelling_to_canonical.get(key, key)] = code
    out: dict[str, int | None] = {}
    for name in source_names:
        key = normalise_person_name(name)
        out[name] = canonical_to_code.get(spelling_to_canonical.get(key, key))
    return out


def name_score(anchor_names: Sequence[str], candidate: str) -> float:
    """Best similarity (0-100) between ``candidate`` and any of the anchor's names."""
    cand_norm, cand_sorted = normalise_person_name(candidate), sorted_tokens(candidate)
    best = 0.0
    for name in anchor_names:
        best = max(
            best,
            similarity(normalise_person_name(name), cand_norm),
            similarity(sorted_tokens(name), cand_sorted),
        )
    return best


def load_player_overrides(path: Path) -> dict[tuple[str, str], int]:
    """Read forced links ``(source, source_id) → fpl_code``; each needs a reason and date."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = ("fpl_code", "source", "source_id", "reason", "date")
    missing = set(required) - set(frame.columns)
    if missing:
        raise DataValidationError(f"{path.name} is missing columns {sorted(missing)}")
    out: dict[tuple[str, str], int] = {}
    for i, rec in enumerate(frame.to_dict(orient="records"), start=2):
        empty = [c for c in required if not str(rec[c]).strip()]
        if empty:
            raise DataValidationError(f"{path.name} line {i}: empty {empty}")
        out[(str(rec["source"]).strip(), str(rec["source_id"]).strip())] = int(rec["fpl_code"])
    return out


def _decide(
    record: SourceRecord,
    anchors_by_team: Mapping[int, Sequence[AnchorPlayer]],
    cfg: EntityResolutionConfig,
) -> Link | ReviewItem:
    candidates = [a for code in record.team_codes for a in anchors_by_team.get(code, ())]
    if not candidates:
        return ReviewItem(
            record.source,
            record.source_id,
            record.name,
            record.team_label,
            None,
            None,
            "no FPL players at this club",
        )
    scored = sorted(
        ((name_score(a.names, record.name), a) for a in candidates),
        key=lambda pair: (-pair[0], pair[1].fpl_code),
    )
    best_score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    review = ReviewItem(
        record.source,
        record.source_id,
        record.name,
        record.team_label,
        best.fpl_code,
        round(best_score, 1),
        "",
    )
    if best_score < cfg.accept_score:
        return _with_reason(review, f"best score {best_score:.1f} below {cfg.accept_score}")
    if best_score - runner_up < cfg.min_margin:
        return _with_reason(review, f"ambiguous: runner-up within {cfg.min_margin}")
    if record.birth_date and best.birth_date and record.birth_date != best.birth_date:
        return _with_reason(review, "date of birth mismatch")
    return Link(record.source, record.source_id, best.fpl_code, round(best_score, 1), "fuzzy")


def _with_reason(item: ReviewItem, reason: str) -> ReviewItem:
    return ReviewItem(
        item.source, item.source_id, item.name, item.team, item.best_candidate, item.score, reason
    )


def resolve(
    anchors: Sequence[AnchorPlayer],
    records: Sequence[SourceRecord],
    cfg: EntityResolutionConfig,
    overrides: Mapping[tuple[str, str], int] | None = None,
) -> Resolution:
    """Match every source record to an FPL anchor or send it to review."""
    known = {a.fpl_code for a in anchors}
    anchors_by_team: dict[int, list[AnchorPlayer]] = {}
    for anchor in anchors:
        anchors_by_team.setdefault(anchor.team_code, []).append(anchor)

    result = Resolution()
    accepted: dict[tuple[str, int], Link] = {}  # (source, fpl_code) → winning link
    for record in records:
        forced = (overrides or {}).get((record.source, record.source_id))
        outcome: Link | ReviewItem
        if forced is not None:
            if forced not in known:
                raise DataValidationError(
                    f"override for {record.source}:{record.source_id} points to unknown "
                    f"fpl_code {forced}"
                )
            outcome = Link(record.source, record.source_id, forced, 100.0, "override")
        else:
            outcome = _decide(record, anchors_by_team, cfg)
        if isinstance(outcome, ReviewItem):
            result.review.append(outcome)
            continue
        key = (outcome.source, outcome.fpl_code)
        incumbent = accepted.get(key)
        if incumbent is None or _beats(outcome, incumbent):
            if incumbent is not None:
                result.review.append(_conflict(incumbent, records))
            accepted[key] = outcome
        else:
            result.review.append(_conflict(outcome, records))

    uf: UnionFind[str] = UnionFind(f"fpl:{a.fpl_code}" for a in anchors)
    for link in accepted.values():
        uf.union(f"fpl:{link.fpl_code}", f"{link.source}:{link.source_id}")
    result.links = sorted(accepted.values(), key=lambda lk: (lk.source, lk.fpl_code))
    result.coverage = _coverage(anchors, uf)
    logger.info(
        "entity resolution done",
        extra={"links": len(result.links), "review": len(result.review)},
    )
    return result


def _beats(challenger: Link, incumbent: Link) -> bool:
    if incumbent.method == "override":
        return False
    return challenger.method == "override" or challenger.score > incumbent.score


def _conflict(loser: Link, records: Sequence[SourceRecord]) -> ReviewItem:
    record = next(r for r in records if (r.source, r.source_id) == (loser.source, loser.source_id))
    return ReviewItem(
        loser.source,
        loser.source_id,
        record.name,
        record.team_label,
        loser.fpl_code,
        loser.score,
        "another record from this source matched the same FPL player",
    )


def _coverage(anchors: Sequence[AnchorPlayer], uf: UnionFind[str]) -> dict[str, float]:
    total = sum(a.minutes for a in anchors)
    out: dict[str, float] = {}
    groups = {uf.find(f"fpl:{a.fpl_code}"): a for a in anchors}
    members: dict[str, set[str]] = {}
    for group in uf.groups():
        root = uf.find(next(iter(group)))
        members[root] = {node.split(":", 1)[0] for node in group}
    for source in MATCH_SOURCES:
        mapped = sum(
            anchor.minutes for root, anchor in groups.items() if source in members.get(root, set())
        )
        out[source] = mapped / total if total > 0 else 0.0
    return out


def fpl_anchors(players: pd.DataFrame, player_match: pd.DataFrame) -> list[AnchorPlayer]:
    """Build anchors from FPL ``parse_players`` and ``parse`` (player-match) outputs."""
    minutes: dict[int, float] = {}
    for rec in player_match.to_dict(orient="records"):
        code = int(rec["fpl_code"])
        minutes[code] = minutes.get(code, 0.0) + float(rec["minutes"] or 0)
    anchors: list[AnchorPlayer] = []
    for rec in players.to_dict(orient="records"):
        code = int(rec["fpl_code"])
        full = f"{rec['first_name']} {rec['second_name']}"
        names = tuple(dict.fromkeys([full, str(rec["web_name"])]))
        anchors.append(AnchorPlayer(code, names, int(rec["team_fpl_code"]), minutes.get(code, 0.0)))
    return anchors


def understat_records(
    player_match: pd.DataFrame, club_codes: Mapping[str, int | None]
) -> list[SourceRecord]:
    """One record per Understat player, blocked on every club they played for."""
    names: dict[int, str] = {}
    teams: dict[int, set[str]] = {}
    for rec in player_match.to_dict(orient="records"):
        pid = int(rec["understat_player_id"])
        names[pid] = str(rec["player_name"])
        teams.setdefault(pid, set()).add(str(rec["team_name"]))
    out: list[SourceRecord] = []
    for pid, name in names.items():
        codes = frozenset(c for t in teams[pid] if (c := club_codes.get(t)) is not None)
        out.append(
            SourceRecord(
                "understat", str(pid), name, codes, team_label=", ".join(sorted(teams[pid]))
            )
        )
    return out


def transfermarkt_records(
    values: pd.DataFrame, club_codes: Mapping[str, int | None]
) -> list[SourceRecord]:
    """One record per Transfermarkt squad player, with date of birth when known."""
    out: list[SourceRecord] = []
    for rec in values.to_dict(orient="records"):
        club = rec.get("tm_club_name")
        club_name = None if club is None or pd.isna(club) else str(club)
        code = club_codes.get(club_name) if club_name else None
        dob = rec.get("birth_date")
        out.append(
            SourceRecord(
                "transfermarkt",
                str(rec["tm_player_id"]),
                str(rec["name"]),
                frozenset({code}) if code is not None else frozenset(),
                team_label=club_name,
                birth_date=dob if isinstance(dob, date) else None,
            )
        )
    return out
