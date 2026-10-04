-- Newest Transfermarkt estimated market value per player and source, with
-- Transfermarkt's own as-of date (CLAUDE.md rules 3 and 10). Sources are kept apart so
-- the engine can apply the configured precedence (override, live, stale snapshot).
WITH ranked AS (
    SELECT
        player_id,
        source,
        value_eur,
        tm_last_updated,
        is_stale,
        reason,
        fetched_at,
        ROW_NUMBER() OVER (
            PARTITION BY player_id, source
            ORDER BY tm_last_updated DESC, fetched_at DESC, id DESC
        ) AS recency
    FROM fact_market_value
    WHERE value_eur IS NOT NULL AND tm_last_updated IS NOT NULL
)
SELECT player_id, source, value_eur, tm_last_updated, is_stale, reason, fetched_at
FROM ranked
WHERE recency = 1
ORDER BY player_id, source
