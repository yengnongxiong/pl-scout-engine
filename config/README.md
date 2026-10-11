# Configuration: the engine's knobs

Every threshold, weight and mapping lives here instead of in the code, so the model can be
tuned without touching Python. Each file is validated when the engine starts; run
`uv run scout config-check` after editing.

| File | What it controls | Example change |
|---|---|---|
| [`settings.yaml`](settings.yaml) | Engine-wide settings: season blending, minutes thresholds, diagnosis and recommendation rules, data-source URLs and polite rate limits, entity-matching thresholds, ML settings. | Rank players only after 900 minutes instead of 600 (`percentile_min_minutes`). |
| [`kpis.yaml`](kpis.yaml) | The KPI catalogue: every metric (label, source, "higher or lower is better", proxy flag) and how much each one matters for each position group. | Make key passes count more for attacking midfielders. |
| [`fit_weights.yaml`](fit_weights.yaml) | How the FitScore combines need-fill, role quality, reliability, style fit and age, plus the upgrade gate and peak-age windows. | Weigh reliability (availability) more heavily. |
| [`positions.yaml`](positions.yaml) | How detailed positions from each source (Transfermarkt, Understat) map onto the eight position groups. | Treat second strikers as attacking midfielders. |
| [`team_aliases.yaml`](team_aliases.yaml) | Other spellings of each club ("Spurs", "Man Utd", "Brighton & Hove Albion"), used for search and for matching clubs across data sources. | Add a nickname so search finds it. |

Weights that must add up to 1 (per position group, and the FitScore components) are checked
on load; a mistake stops the engine with a clear message instead of producing quietly wrong
numbers.
