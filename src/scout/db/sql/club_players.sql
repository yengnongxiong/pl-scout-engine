-- Current-season minutes per club x player from FPL rows (minutes earned at that club),
-- with position group, date of birth and the newest known contract expiry.
WITH current_season AS (
    SELECT season_id FROM dim_season WHERE is_current
),
club_minutes AS (
    SELECT f.team_id, f.player_id, SUM(f.minutes) AS minutes
    FROM fact_player_match AS f
    JOIN dim_match AS m ON m.match_id = f.match_id
    WHERE f.source = 'fpl' AND m.season_id IN (SELECT season_id FROM current_season)
    GROUP BY f.team_id, f.player_id
),
latest_status AS (
    SELECT
        player_id,
        contract_expiry,
        ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY fetched_at DESC) AS recency
    FROM fact_player_status
)
SELECT
    c.team_id,
    c.player_id,
    p.canonical_name,
    p.position_group,
    p.birth_date,
    s.contract_expiry,
    c.minutes
FROM club_minutes AS c
JOIN dim_player AS p ON p.player_id = c.player_id
LEFT JOIN latest_status AS s ON s.player_id = c.player_id AND s.recency = 1
ORDER BY c.team_id, c.minutes DESC, c.player_id
