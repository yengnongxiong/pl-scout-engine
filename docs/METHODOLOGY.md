# Methodology

How PL Scout Engine turns free match data into club needs, shortlists and scouting reports.
This is the method as implemented; the requirements behind it are in [`PRD.md`](../PRD.md) §8–9,
and every tunable number lives in [`config/`](../config) rather than in code. The dashboard's
**Methodology & data** page shows the live values, the freshness of each source and the
known limitations.

The guiding rule: **no number without a receipt.** Every stored metric row carries its
`source` and `fetched_at`; Transfermarkt estimated market values also carry Transfermarkt's own
as-of date; missing data stays missing and is shown as "Not available", never as 0.

## 1. Data and layers

| Layer | What happens | Code |
|---|---|---|
| Bronze | Raw snapshots per source, timestamped with a checksum (`data/raw/`) | `ingest/` |
| Silver | Parse, validate (pandera), resolve players across sources | `transform/` |
| Gold | SQLAlchemy star schema on SQLite (Postgres-compatible SQL), Alembic migrations | `db/` |
| Features | Per 90 → blend → shrink → possession adjustment → percentiles | `features/`, `db/sql/` |
| Engines / ML | Diagnosis, FitScore shortlists, role archetypes, similarity, value model | `engines/`, `ml/` |
| Reports | Fact sheet → template report → grounding validator | `reports/` |
| API / web | Read-only FastAPI over the warehouse; React + TypeScript dashboard | `api/`, `web/` |

Sources (PRD §7.1): the official Fantasy Premier League API (minutes, starts, FPL xG/xA,
tackles, recoveries, clearances/blocks/interceptions, availability), the vaastav FPL archive
(past seasons), Understat via `soccerdata` (xG, npxG, xA, xGChain, xGBuildup, shots, key passes,
PPDA, deep completions), FotMob via `soccerdata` (possession), Transfermarkt through a
self-hosted `transfermarkt-api` (estimated market value, position, date of birth, contract) with
the `transfermarkt-datasets` export as a labelled-stale fallback, and manual override CSVs that
need a reason and a date. FBref advanced stats are not used (removed January 2026).

Players are joined on FPL `code` (stable across seasons; FPL `id` is not). Names from other
sources are matched within the same club after `unidecode` normalisation, with fuzzy matching,
a date-of-birth check, an override file and a union-find merge; anything uncertain goes to
`entity_map_review` instead of being guessed. `scout doctor` reports the share of FPL minutes
mapped per source (target ≥ 98%).

## 2. Feature layer (PRD §8.1–8.6)

**Per 90.** Counting stats are divided by minutes / 90, never per match (double gameweeks and
substitute appearances distort per-match rates). Each source uses its own minutes.

**Season blending** (early-season stability):

```
blended = (m_cur · r_cur + λ · min(m_prev, cap) · r_prev) / (m_cur + λ · min(m_prev, cap))
```

λ = `blend_lambda` (0.5) and cap = `prev_season_minutes_cap` (2,000). Early in the season last
season dominates; by mid-season this season does. The denominator is the player's
**effective minutes**, shown next to every rate. Mode `current` uses this season alone.

**Shrinkage** (small samples, empirical Bayes):

```
shrunk = (n · rate + k · prior) / (n + k),   n = effective minutes / 90
```

The prior is the minutes-weighted mean of the player's position group; `k` comes from the KPI
(`shrinkage_k`) or `default_shrinkage_k` (10 nineties). Rankings use shrunk rates, displays show
the rate itself next to its minutes.

**Possession adjustment** (defensive volume): each match's tackles, recoveries and
clearances/blocks/interceptions are multiplied by `0.5 / opponent possession share`, clipped to
[0.67, 1.5]. Without possession data a match stays raw and the KPI is flagged **unadjusted**.

**Percentiles** use SQL `PERCENT_RANK` semantics within the position group, among players with at
least `percentile_min_minutes` (600) effective minutes; "lower is better" KPIs are ranked on the
negated value so a higher percentile is always better. `n_peers` is always returned with a
percentile. The SQL (`db/sql/percentiles.sql`) has a pandas twin tested to give the same answer.

**Positions.** Transfermarkt's detailed position maps to eight groups (GK, CB, FB, DM, CM, AM,
W, ST) in `config/positions.yaml`; the coarse FPL element type is a fallback. Goalkeepers have
their own, clearly limited group (below).

## 3. KPIs

Defined once in `config/kpis.yaml`, each with a source and an `is_proxy` flag; position groups
weight them (weights sum to 1 per group). Proxies are badged everywhere they appear:

- **Pressing (player level)** is not freely available, so the proxy is possession-adjusted
  defensive activity: tackles + recoveries, plus clearances/blocks/interceptions for CB and FB.
  Team pressing uses Understat PPDA, a real metric.
- **Ball progression** uses xGBuildup and xGChain per 90 as proxies; true progressive passes need
  event data.
- **xA** comes from Understat (xG of the shots a player's key passes created), which is not the
  FPL/Opta definition; each KPI uses one source and says which.

**Goalkeepers** (stretch S2) are rated on what free data allows, and every goalkeeper rating
carries a "limited metrics" caveat: goals prevented vs xG conceded per 90 (xG conceded on the
pitch minus goals conceded; a **proxy** for shot-stopping, because post-shot xG is not free and
pre-shot xG also reflects the finishing faced), save percentage (saves / (saves + goals
conceded)), saves per 90 and xG conceded on the pitch. There are no distribution, claiming or
sweeping numbers. Goalkeepers are kept out of the outfield role archetypes.

Team KPIs (xG for/against, PPDA, PPDA allowed, deep completions, set-piece and open-play xG)
come from Understat and are mapped to the position groups most responsible for them.

## 4. Club diagnosis (PRD §8.8)

1. **Group score** per club × position group × KPI: the minutes-weighted mean percentile of the
   club's players, weighted by minutes *for this club* (a mid-season signing only counts for the
   minutes played here).
2. **Benchmark**: the same score for the benchmark clubs. Default: the top six of last season's
   table (computed from results with a `RANK` window), excluding the club itself; toggles for
   top four, the whole league, or a custom list.
3. **Gap** = benchmark − club per KPI; **severity** = Σ weight × max(0, gap). Being better on one
   KPI never cancels a weakness on another.
4. **Weak links**: players with ≥ 40% of available minutes and a percentile < 30 on a KPI with
   weight ≥ 0.20.
5. **Risks**: depth (one player > 80% of group minutes and no backup above the 40th percentile),
   age (minutes-weighted age ≥ 30), contract (key player's contract ends within 12 months, when
   known).
6. **Team-level needs**: team KPI percentiles among this season's clubs; shortfalls against the
   benchmark are attached to the responsible groups as context.

Every need carries evidence rows: player, KPI, per-90 values, percentile, peers, minutes, source
and as-of.

## 5. Shortlists and FitScore (PRD §8.9)

The candidate pool is every Premier League player in the need's group at another club who
passes the hard filters (Transfermarkt estimated market value budget, age range, minimum
minutes, FPL availability, excluded clubs). Players dropped by a filter are counted per reason;
a budget filter drops players *without* a market value rather than assuming they are cheap.

```
FitScore (0–100) = 0.40·NeedFill + 0.25·RoleQuality + 0.15·Reliability + 0.10·StyleFit + 0.10·AgeProfile
```

- **NeedFill**: the candidate's percentiles on the KPIs where the club trails, weighted by
  KPI weight × gap (when the club trails on nothing, the group weights).
- **RoleQuality**: the overall position-weighted percentile.
- **Reliability**: 0.6 × minutes volume (effective minutes / 2,500, capped) + 0.4 × availability
  (FPL chance of playing, else a value per FPL status).
- **StyleFit**: cosine similarity of the candidate's current team style vector with the target
  club's (possession share, PPDA, deep completions per possession share as a directness proxy),
  each standardised across clubs, mapped from [-1, 1] to [0, 100].
- **AgeProfile**: 100 inside the group's peak-age window, minus 15 points per year outside.

A component without evidence is dropped and the remaining weights are renormalised; the
breakdown shows the weights actually used. **Upgrade gate**: the candidate must beat the
incumbent (the club's minutes leader in the group) on NeedFill by ≥ 15 points; otherwise the
move is "sideways" and hidden unless asked for. The top k are picked with a hand-written
bounded min-heap (`dsa/heap_topk.py`).

## 6. Machine learning (PRD §8.10)

- **Role archetypes**: a Gaussian Mixture Model (diagonal covariance) on standardised shrunk
  KPI rates of players with ≥ 900 effective minutes; k chosen by BIC in 6–12; clusters labelled by
  their two most extreme KPIs ("high Build-up involvement, high Recoveries"), renameable in config.
  Diagnostics: BIC curve, silhouette, adjusted Rand index across seeds.
- **Similar players**: cosine similarity of z-scored KPI vectors scaled by √weight, within the
  position group, top-k by heap. Brute force is the default because at ~600 players it beats the
  hand-written k-d tree (`scripts/bench_knn.py`).
- **Stats-implied value**: `HistGradientBoostingRegressor` on log(Transfermarkt estimated market
  value at season end) from age, age², position group, minutes share, blended per-90 output and
  club points per game. Time-based split (train on earlier seasons, test on the latest), compared
  with a baseline (median by position group × age bucket) on MAE (log scale) and median absolute
  % error. 10th/90th-percentile quantile models give the band: a Transfermarkt value below it is
  **Undervalued**, above it **Premium**, inside it **Fair**. It is a stats-implied value, not a fee
  prediction: the model learns the market's own biases.

- **Age curves** (delta method): for players with ≥ 900 minutes in two consecutive past seasons,
  the change in each per-90 rate (FPL xG, xA, goals, assists) is assigned to the player's age at
  the end of the first season and weighted by the harmonic mean of the two seasons' minutes; the
  weighted mean per age (only with ≥ 15 pairs) gives the typical next-season change, and the
  player page projects next season as the blended rate plus that change. The delta method only
  sees players good enough to keep playing, so declines are understated (survivorship bias).

All fits are seeded. `scout train` saves each model with a metadata JSON (data window, features,
metrics, seed, git SHA), stores role labels and value bands in the warehouse, and writes
[`docs/EVALUATION.md`](EVALUATION.md). A model is never trained on too little data; it is
skipped and the reason recorded.

## 7. Scouting reports (PRD §9)

1. **Fact sheet**: every number and claim the report may use, each with its receipt
   (`reports/facts.py`), including the caveats that apply (small sample, proxy metrics, unadjusted
   defensive numbers, stale or missing market value, no previous season in the blend).
2. **Template report**: Jinja2 plus phrase banks keyed to percentile bands (≥ 90 elite, 75–89
   strong, 50–74 above average, 25–49 below average, < 25 weak), with a seeded choice so reports
   vary without being random.
3. **Optional local LLM**: with `REPORT_ENGINE=ollama` and a local model, the template report is
   rewritten for fluency at low temperature with an instruction to add no facts. Never required.
4. **Grounding validator**: every number (at the precision shown, with its sign), euro amount,
   date, season and capitalised name in the output must exist in the fact sheet. Any violation
   discards the rewrite, shows the template report and logs why. The template itself is validated
   too, and the tests inject fake numbers and names to prove they are rejected.

## 8. Known limitations

- Player-level pressing and ball progression are proxies (see §3).
- Possession adjustment depends on FotMob; matches without possession stay unadjusted.
- Transfermarkt estimated market values are estimates; the datasets fallback stopped updating
  in mid-2026 and is labelled stale.
- The value model is trained on past Premier League seasons of current players (survivorship
  bias) and learns market biases.
- Candidates are Premier League players only. Goalkeeper ratings are limited (no post-shot xG,
  distribution, claiming or sweeping data) and always say so.
- FPL fields are undocumented and can change; `scout doctor` validates the schema every run.
