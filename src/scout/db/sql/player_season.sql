-- Player x season x club x source totals (PRD §8.1, CLAUDE.md "Known gotchas").
-- Grouping by club keeps movers' minutes split by the club they were earned at.
-- SUM over only-NULL values stays NULL: missing data never becomes 0.
WITH match_rows AS (
    SELECT
        f.player_id,
        m.season_id,
        f.team_id,
        f.source,
        f.minutes,
        CASE WHEN f.started IS NULL THEN NULL WHEN f.started THEN 1 ELSE 0 END AS start_flag,
        f.goals, f.assists, f.xg, f.npxg, f.xa, f.shots, f.key_passes,
        f.xg_chain, f.xg_buildup, f.tackles, f.recoveries, f.cbi, f.def_contribution,
        f.xgc_on_pitch, f.yellow_cards, f.red_cards, f.fetched_at
    FROM fact_player_match AS f
    JOIN dim_match AS m ON m.match_id = f.match_id
)
SELECT
    player_id,
    season_id,
    team_id,
    source,
    COUNT(*) AS matches,
    SUM(minutes) AS minutes,
    SUM(start_flag) AS starts,
    SUM(goals) AS goals,
    SUM(assists) AS assists,
    SUM(xg) AS xg,
    SUM(npxg) AS npxg,
    SUM(xa) AS xa,
    SUM(shots) AS shots,
    SUM(key_passes) AS key_passes,
    SUM(xg_chain) AS xg_chain,
    SUM(xg_buildup) AS xg_buildup,
    SUM(tackles) AS tackles,
    SUM(recoveries) AS recoveries,
    SUM(cbi) AS cbi,
    SUM(def_contribution) AS def_contribution,
    SUM(xgc_on_pitch) AS xgc_on_pitch,
    SUM(yellow_cards) AS yellow_cards,
    SUM(red_cards) AS red_cards,
    MAX(fetched_at) AS fetched_at
FROM match_rows
GROUP BY player_id, season_id, team_id, source
ORDER BY player_id, season_id, team_id, source
