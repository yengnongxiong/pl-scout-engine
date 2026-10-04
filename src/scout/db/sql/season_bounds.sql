-- First and last kickoff and the number of matches per season (PRD §8.10 step 3: the
-- season's last kickoff anchors the end-of-season valuation used as a training label).
SELECT
    season_id,
    MIN(kickoff) AS first_kickoff,
    MAX(kickoff) AS last_kickoff,
    COUNT(*) AS matches
FROM dim_match
WHERE kickoff IS NOT NULL
GROUP BY season_id
ORDER BY season_id
