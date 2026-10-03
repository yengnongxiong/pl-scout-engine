-- Team x season totals from one source for team-level KPIs (PRD §8.7 Team row, §8.8 step 7).
-- Every column keeps its own match count: a match where a value is missing (for example
-- no shot events, so no set-piece split) counts in neither the total nor the denominator,
-- so a rate is over the matches that have data (CLAUDE.md rule 2). as_of is the newest
-- fetched_at behind the row (rule 3).
SELECT
    f.team_id,
    m.season_id,
    COUNT(*) AS matches,
    SUM(f.xg) AS xg_total, COUNT(f.xg) AS xg_matches,
    SUM(f.xga) AS xga_total, COUNT(f.xga) AS xga_matches,
    SUM(f.npxg) AS npxg_total, COUNT(f.npxg) AS npxg_matches,
    SUM(f.npxga) AS npxga_total, COUNT(f.npxga) AS npxga_matches,
    SUM(f.ppda) AS ppda_total, COUNT(f.ppda) AS ppda_matches,
    SUM(f.ppda_allowed) AS ppda_allowed_total, COUNT(f.ppda_allowed) AS ppda_allowed_matches,
    SUM(f.deep) AS deep_total, COUNT(f.deep) AS deep_matches,
    SUM(f.deep_allowed) AS deep_allowed_total, COUNT(f.deep_allowed) AS deep_allowed_matches,
    SUM(f.set_piece_xg) AS set_piece_xg_total, COUNT(f.set_piece_xg) AS set_piece_xg_matches,
    SUM(f.set_piece_xga) AS set_piece_xga_total,
    COUNT(f.set_piece_xga) AS set_piece_xga_matches,
    SUM(f.open_play_xga) AS open_play_xga_total,
    COUNT(f.open_play_xga) AS open_play_xga_matches,
    MAX(f.fetched_at) AS as_of
FROM fact_team_match AS f
JOIN dim_match AS m ON m.match_id = f.match_id
WHERE f.source = :source
GROUP BY f.team_id, m.season_id
ORDER BY m.season_id, f.team_id
