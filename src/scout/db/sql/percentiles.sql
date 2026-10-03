-- Within-position-group percentiles (PRD §8.6), 0-100, higher always better.
-- Only players meeting :min_minutes with a known value are ranked; n_peers is exposed
-- (CLAUDE.md rule 8). Inverse KPIs (e.g. xG conceded, cards) are ranked on the negated
-- value so a higher percentile is always better. Input: kpi_values(player_id,
-- position_group, kpi, value, minutes, higher_is_better).
WITH eligible AS (
    SELECT
        player_id,
        position_group,
        kpi,
        value,
        CASE WHEN higher_is_better THEN value ELSE -value END AS score
    FROM kpi_values
    WHERE minutes >= :min_minutes
      AND value IS NOT NULL
      AND position_group IS NOT NULL
)
SELECT
    player_id,
    position_group,
    kpi,
    value,
    100.0 * PERCENT_RANK() OVER (PARTITION BY position_group, kpi ORDER BY score)
        AS percentile,
    COUNT(*) OVER (PARTITION BY position_group, kpi) AS n_peers
FROM eligible
ORDER BY position_group, kpi, player_id
