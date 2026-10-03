-- Possession-adjusted defensive totals per player x season x club x source (PRD §8.4).
-- Each match is scaled by even_share / opponent possession share, clipped to
-- [clip_min, clip_max]. Matches without possession keep the raw value and are counted
-- in unadjusted_matches so the KPI can be flagged "unadjusted" (CLAUDE.md rule 9).
WITH player_matches AS (
    SELECT
        f.player_id,
        m.season_id,
        f.team_id,
        f.source,
        f.match_id,
        f.tackles,
        f.recoveries,
        f.cbi,
        CASE WHEN f.team_id = m.home_team_id THEN m.away_team_id ELSE m.home_team_id END
            AS opponent_team_id
    FROM fact_player_match AS f
    JOIN dim_match AS m ON m.match_id = f.match_id
    WHERE f.source IN ('fpl', 'vaastav')
),
possession AS (
    SELECT match_id, team_id, possession
    FROM fact_team_match
    WHERE source = 'fotmob' AND possession IS NOT NULL AND possession > 0
),
adjusted AS (
    SELECT
        pm.*,
        CASE
            WHEN p.possession IS NULL THEN NULL
            WHEN :even_share / p.possession < :clip_min THEN :clip_min
            WHEN :even_share / p.possession > :clip_max THEN :clip_max
            ELSE :even_share / p.possession
        END AS multiplier
    FROM player_matches AS pm
    LEFT JOIN possession AS p
        ON p.match_id = pm.match_id AND p.team_id = pm.opponent_team_id
)
SELECT
    player_id,
    season_id,
    team_id,
    source,
    COUNT(*) AS matches,
    SUM(CASE WHEN multiplier IS NULL THEN 1 ELSE 0 END) AS unadjusted_matches,
    SUM(tackles * COALESCE(multiplier, 1.0)) AS tackles_padj,
    SUM(recoveries * COALESCE(multiplier, 1.0)) AS recoveries_padj,
    SUM(cbi * COALESCE(multiplier, 1.0)) AS cbi_padj
FROM adjusted
GROUP BY player_id, season_id, team_id, source
ORDER BY player_id, season_id, team_id, source
