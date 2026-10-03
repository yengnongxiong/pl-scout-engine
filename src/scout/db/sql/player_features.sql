-- Materialised KPI features for one season mode (blended or current).
SELECT
    player_id, position_group, kpi, source, raw_p90, value, shrunk, percentile, n_peers,
    minutes, effective_minutes, is_proxy, padj_status, as_of
FROM player_season_features
WHERE season_mode = :season_mode
ORDER BY player_id, kpi
