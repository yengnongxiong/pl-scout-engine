-- One row per player with current-season FPL minutes: current club (the club of the
-- player's latest current-season match), position, date of birth and the newest FPL
-- availability snapshot with its fetched_at (PRD §8.9 candidate pool and Reliability).
WITH current_season AS (
    SELECT season_id FROM dim_season WHERE is_current
),
appearances AS (
    SELECT
        f.player_id,
        f.team_id,
        f.minutes,
        -- Matches without a kickoff sort last on both SQLite and Postgres.
        ROW_NUMBER() OVER (
            PARTITION BY f.player_id
            ORDER BY CASE WHEN m.kickoff IS NULL THEN 1 ELSE 0 END, m.kickoff DESC,
                m.match_id DESC
        ) AS recency
    FROM fact_player_match AS f
    JOIN dim_match AS m ON m.match_id = f.match_id
    WHERE f.source = 'fpl' AND m.season_id IN (SELECT season_id FROM current_season)
),
season_minutes AS (
    SELECT player_id, SUM(minutes) AS season_minutes
    FROM appearances
    GROUP BY player_id
),
latest_status AS (
    SELECT
        player_id,
        fpl_status,
        chance_of_playing,
        contract_expiry,
        fetched_at,
        ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY fetched_at DESC) AS recency
    FROM fact_player_status
)
SELECT
    p.player_id,
    p.canonical_name,
    p.position_group,
    p.birth_date,
    a.team_id AS current_team_id,
    sm.season_minutes,
    s.fpl_status,
    s.chance_of_playing,
    s.contract_expiry,
    s.fetched_at AS status_as_of
FROM appearances AS a
JOIN dim_player AS p ON p.player_id = a.player_id
JOIN season_minutes AS sm ON sm.player_id = a.player_id
LEFT JOIN latest_status AS s ON s.player_id = a.player_id AND s.recency = 1
WHERE a.recency = 1
ORDER BY p.player_id
