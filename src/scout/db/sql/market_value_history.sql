-- Every stored Transfermarkt estimated market value with its own as-of date, all sources
-- (PRD §8.10 step 3: training labels are the valuation nearest each season's end).
-- Rows without a value or an as-of date carry no receipt and are left out (rule 3).
SELECT player_id, source, value_eur, tm_last_updated, is_stale, fetched_at
FROM fact_market_value
WHERE value_eur IS NOT NULL AND tm_last_updated IS NOT NULL
ORDER BY player_id, tm_last_updated, source
