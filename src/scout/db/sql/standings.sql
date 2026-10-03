-- League table for one season from played matches (benchmark selection, PRD §8.8 step 2).
-- 3 points for a win, 1 for a draw; ranked by points, then goal difference, then goals
-- for (RANK keeps genuine ties level). Matches without a score are not counted.
WITH results AS (
    SELECT home_team_id AS team_id, home_score AS goals_for, away_score AS goals_against
    FROM dim_match
    WHERE season_id = :season_id AND home_score IS NOT NULL AND away_score IS NOT NULL
    UNION ALL
    SELECT away_team_id AS team_id, away_score AS goals_for, home_score AS goals_against
    FROM dim_match
    WHERE season_id = :season_id AND home_score IS NOT NULL AND away_score IS NOT NULL
),
totals AS (
    SELECT
        team_id,
        COUNT(*) AS played,
        SUM(CASE WHEN goals_for > goals_against THEN 3
                 WHEN goals_for = goals_against THEN 1
                 ELSE 0 END) AS points,
        SUM(goals_for) AS goals_for,
        SUM(goals_against) AS goals_against
    FROM results
    GROUP BY team_id
)
SELECT
    team_id,
    played,
    points,
    goals_for,
    goals_against,
    goals_for - goals_against AS goal_difference,
    RANK() OVER (
        ORDER BY points DESC, goals_for - goals_against DESC, goals_for DESC
    ) AS position
FROM totals
ORDER BY position, team_id
