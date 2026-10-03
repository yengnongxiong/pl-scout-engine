-- Scored matches per club in the current season (available minutes = matches x 90).
WITH current_season AS (
    SELECT season_id FROM dim_season WHERE is_current
),
sides AS (
    SELECT home_team_id AS team_id FROM dim_match
    WHERE season_id IN (SELECT season_id FROM current_season) AND home_score IS NOT NULL
    UNION ALL
    SELECT away_team_id AS team_id FROM dim_match
    WHERE season_id IN (SELECT season_id FROM current_season) AND away_score IS NOT NULL
)
SELECT team_id, COUNT(*) AS matches
FROM sides
GROUP BY team_id
ORDER BY team_id
