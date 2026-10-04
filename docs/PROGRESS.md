# Progress
Status: IN_PROGRESS            <!-- IN_PROGRESS or COMPLETE -->
Active session: 20261003T2337Z-49bb started 2026-10-03T23:37:32Z
Current milestone: M5 (M0 web items blocked on npm)

## Plan for this session
- M4-05 team-level needs (Understat team KPIs per 90, league percentiles, benchmark gap, mapped to responsible groups)
- Then start M5 (recommendation engine) if time allows

## Task queue (current milestone)
- [x] M0-01 Apply ADR-0001 edits to PRD, bump to v1.1 + changelog — PRD diff matches ADR list
- [x] M0-02 Python skeleton: pyproject (uv), src/scout package, errors.py, config.py (pydantic-settings + YAML), Typer CLI with `--help`, conftest network guard — `uv run scout --help`, pytest, ruff, mypy pass
- [x] M0-03 config/*.yaml stubs (settings, kpis, fit_weights, positions, team_aliases) loaded + validated by config.py — unit tests pass
- [ ] M0-04 web/ scaffold: Vite + React + TS strict, ESLint, Prettier, Vitest + RTL, Tailwind — lint/typecheck/test/build pass
- [ ] M0-05 FastAPI stub (`/health`) + `scout export-openapi` + `npm run gen:api` (openapi-typescript) — generated files committed, no drift
  - Note: Python half done (FastAPI `/health`, error schema, CORS, `scout api`, `scout export-openapi`; CI-verified). Remaining: commit `web/openapi.json`, `npm run gen:api` with openapi-typescript, `contract` CI job. Needs npm (blocked).
- [ ] M0-06 CI workflow (python, web, contract jobs) + ADR template + README stub + Makefile + .env.example + .gitignore — workflow file valid; local equivalents pass
  - Note: CI `python` job, Makefile, .gitignore, .env.example, ADR template and README stub done. Remaining: `web` and `contract` jobs once web/ exists.


### M1 (started early: remaining M0 items are blocked on npm; Python-only and independent)
- [x] M1-01 `dsa/token_bucket.py` + `dsa/lru_cache.py` with complexity docstrings and reference tests — pytest passes
- [x] M1-02 `ingest/base.py`: SourceAdapter ABC, raw snapshot store (timestamped, checksum), TTL cache, polite httpx client (User-Agent, token bucket, tenacity retries, interstitial detection) — unit tests with mocked transport
- [x] M1-03 FPL adapter: bootstrap-static + element-summary + fixtures parse to validated DataFrames keyed on `code`; season derived from events; trimmed synthetic fixtures; contract + schema-changed tests
- [x] M1-04 vaastav history adapter (per-gameweek CSV) with fixture contract tests
- [x] M1-05 Understat adapter (player match, team match incl. PPDA/deep) via soccerdata, fixture contract tests
  - Note: understat.com is probably blocked here and PyPI is blocked, so soccerdata's current output schema can't be checked live. Build synthetic fixtures from soccerdata's documented `read_player_match_stats` / `read_team_match_stats` columns, parse defensively (required vs optional columns), and add a line to Questions asking the owner to run one live fetch.
- [x] M1-06 FotMob possession adapter, fixture contract tests
- [x] M1-07a Transfermarkt live adapter via self-hosted transfermarkt-api: club search by name/alias, squads, market value with TM as-of = latest history point, position/DOB/contract; value/date parsers — contract tests
- [x] M1-07b transfermarkt-datasets snapshot fallback (source=snapshot, is_stale=True) + market_value_overrides.csv loader (source=override, reason + date required) — tests
- [x] M1-08 StatsBomb open-data loader (dev) + `scout ingest --source` CLI wiring with per-session request caps

### M2 Warehouse
- [x] M2-01 `dsa/union_find.py` + `dsa/levenshtein.py` (DP; agrees with rapidfuzz) with complexity docstrings and reference tests
- [x] M2-02 `db/models.py` SQLAlchemy 2.0 star schema (PRD §11) + `db/session.py` + Alembic initial migration — create_all and `alembic upgrade head` on SQLite in tests
- [x] M2-03 `transform/validate.py` pandera schemas per staged table + validation report; `transform/clean.py` name normalisation
- [x] M2-04 `transform/entity_resolution.py`: club blocking, unidecode, fuzzy match, DOB confirm, overrides CSV, union-find merge, unresolved → entity_map_review — coverage report
- [x] M2-05a `db/load.py` dimension loaders: seasons, teams (FPL + source ids), players (resolved ids, TM position → group, FPL fallback, DOB), matches (FPL fixtures; Understat/FotMob joined on season + home + away); idempotent
- [x] M2-05b fact loaders: fact_player_match (FPL + Understat rows), fact_team_match (Understat + FotMob possession), fact_market_value (live/snapshot/override precedence kept as rows), fact_player_status, source_snapshot rows, entity_map_review; idempotent delete-and-insert per source
- [x] M2-05c previous-season FPL defensive data from vaastav: map season fixture ids to matches via (season, home, away)
- [x] M2-06 `scout build` raw → validated → warehouse with `--allow-invalid` (logged); fixture end-to-end integration test; a validation failure stops the build
- [x] M2-07 `scout doctor`: freshness, coverage, validation status, missing FPL fields

### M3 Feature layer
- [x] M3-01 `features/per90.py`, `blend.py`, `shrinkage.py`, `possession.py` pure functions (PRD §8.1-8.4) with hand-calculated tests
- [x] M3-02 `db/sql/player_season.sql` (CTEs) per player × season × club totals by source + pandas twin test; club splits for movers
- [x] M3-03 possession-adjusted defensive totals per match (opponent possession from fotmob; clipped multiplier; unadjusted flag) in SQL + pandas twin
- [x] M3-04 `features/percentiles.py` + `db/sql/percentiles.sql` (PERCENT_RANK within position group, minutes threshold, inverse flip, n_peers) + twin test
- [x] M3-05 `player_season_features` table (migration 0002) materialised by `scout build` from `config/kpis.yaml` (raw per-90, blended, shrunk, percentiles, minutes, n_peers, flags)
  - Design notes (next session): store long format `player_season_features(player_id, season_mode, position_group, kpi, raw_p90, value, shrunk, percentile, n_peers, minutes, blended_minutes, is_proxy, padj_status, source, as_of)` unique (player_id, season_mode, kpi), via migration 0002 (extend the compare_metadata test). KPI sources: `fpl` = current `fpl` rows + previous-season `vaastav` rows; `understat` = both seasons. Per-90 uses each source's own minutes. Defensive KPIs come from `defensive_padj.sql`; `def_activity` = tackles + recoveries, plus CBI for the groups listed in a new `kpis.yaml` key (`def_activity_includes_cbi_groups: [CB, FB]`, PRD §7.2). `cards` = yellow + red. `npxg_per_shot` = npxg / shots (not per 90). Blend with `features/blend.py` (lambda, cap from config), shrink toward the minutes-weighted group mean of blended rates (k from KPI or default), then percentiles on shrunk values among blended minutes ≥ `percentile_min_minutes`. season_mode ∈ {blended, current}.
- M0-01, M0-02, M0-03 (2026-10-03); Python halves of M0-05/M0-06.
- M1-01 to M1-04 (2026-10-03).

### M4 Diagnosis engine
- [x] M4-01 `db/sql/standings.sql` (points/GD/GF, RANK window) + pandas twin; `engines/benchmark.py` picks benchmark clubs (top6/top4/league/custom, excluding the selected club; sizes in config)
- [x] M4-02 `engines/diagnosis.py` group scores: minutes-weighted mean percentile per club x position group x KPI (weights = current-season minutes for that club), benchmark score, gap and need severity (PRD §8.8 steps 1-3) — hand-calculated tests
- [x] M4-03 weak links + risk flags (depth, age, contract) with config thresholds (§8.8 steps 4-5)
- [x] M4-04 Need/Evidence objects with source + as-of on every evidence row, team-level needs mapped to responsible groups (step 7), deterministic ranking; `scout diagnose --team` CLI — fixture end-to-end test (team-level part split out to M4-05)
- [x] M4-05 Team-level needs (§8.8 step 7): team KPIs per 90 from fact_team_match (Understat), league percentile per KPI (inverse flipped), club vs benchmark gap, mapped to `responsible_groups` and added to `Diagnosis.team_needs`; shown by `scout diagnose`

### M5 Recommendation engine + ML
- [x] M5-01 `dsa/heap_topk.py` (bounded min-heap, O(n log k)) with complexity docstring + reference test vs `heapq.nlargest`/sorted, ties deterministic
- [x] M5-02 `engines/fit.py` pure FitScore components (NeedFill, RoleQuality, Reliability, StyleFit cosine, AgeProfile vs `peak_age`) + weighted total + upgrade gate (PRD §8.9) — hand-calculated tests; missing component renormalises, never 0
- [x] M5-03 Team style vectors (FotMob possession, PPDA, directness proxy) per club x season in SQL + pandas twin; config lists the style features
- [x] M5-04a `db/sql/player_profiles.sql` (current club = latest current-season FPL match, season minutes, newest FPL status) + `db/sql/market_values.sql` (newest valuation per player x source with TM as-of) with pandas twins
- [x] M5-04b `engines/recommend.py` candidate pool (need's group, other clubs, hard filters: max TM value, age range, min minutes, availability, exclude clubs), market-value precedence from config, incumbent = club's minutes leader in the group, upgrade gate tag, heap top-k ranking, receipts (TM value + TM as-of, minutes, source); `scout recommend TEAM --need GROUP` — fixture integration test
- [x] M5-05 deps numpy + scikit-learn; `ml/similarity.py` cosine on standardised KPI-weighted vectors, top-k via heap_topk; `dsa/kdtree.py` + reference test; `scripts/bench_knn.py`
- [ ] M5-06 `ml/roles.py` GMM on standardised per-90 vectors (≥ roles_min_minutes), k by BIC in [gmm_k_min, gmm_k_max], seeded; auto-labels from distinguishing features + rename map; silhouette + ARI stability across seeds
- [ ] M5-07 `ml/value_model.py` HistGradientBoosting on log(TM value), time-based split, baseline median by position x age bucket, q10/q90 band, Undervalued/Fair/Premium label; artefacts + metadata JSON (window, features, metrics, git SHA)
- [ ] M5-08 `scout train` writes models + metadata + `docs/EVALUATION.md` (value model vs baseline, GMM diagnostics, similarity examples) — fixture run in tests

## Done
- M0-01, M0-02, M0-03 (2026-10-03); Python halves of M0-05/M0-06.
- M1-01 to M1-08 (2026-10-03): all ingestion adapters plus `scout ingest`.
- M2-01 to M2-07 (2026-10-03): warehouse, entity resolution, validation, `scout build`, `scout doctor`.
- M3-01 to M3-04 (2026-10-03): per-90/blend/shrink/possession maths, player-season and possession-adjusted SQL, percentiles.
- M3-05, M4-01 to M4-05 (2026-10-03): player_season_features, benchmark clubs, group scores and gaps, weak links, risks, ranked needs with receipts, team-level needs; `scout diagnose`.

## Blocked
- **Package registries blocked in the cloud sandbox** (2026-10-03): pypi.org and registry.npmjs.org return `403 host_not_allowed` from the egress proxy, so `uv sync` / `npm ci` can't run. Python checks ran locally against preinstalled packages (ruff, pytest and mypy all pass apart from the missing typer/types-PyYAML imports). GitHub Actions CI is the authoritative check. M0-04/M0-05 (web scaffold, `package-lock.json`, FastAPI + OpenAPI) need npm/PyPI and wait until the owner allows those hosts. `uv.lock` isn't committed yet for the same reason; generate it once PyPI is reachable.

## Questions for Yengnong (non-blocking; default chosen)
- `ingest.base_urls.transfermarkt_datasets` defaults to the dataset's public R2 export URL. I couldn't verify it from the sandbox; please confirm or correct it in `config/settings.yaml`. Default: use it as is; a failed fetch just means no stale fallback.
- Please run the self-hosted `felipeall/transfermarkt-api` on :8001 (or change `ingest.base_urls.transfermarkt`) before `scout ingest --source transfermarkt`.
- Please allow `pypi.org`, `files.pythonhosted.org` and `registry.npmjs.org` (or the Trusted network level) in the routine's environment. Default until then: Python work verified via CI, web work paused.

## Decisions log (minor)
- 2026-10-04: Similar players (PRD §8.10): vectors of the player's position-group KPIs (shrunk rates), z-scored across the group's ranked players and scaled by sqrt(KPI weight), so each KPI counts in proportion to its weight in the cosine. Only players ranked on every weighted KPI take part (no imputation); search is brute force + heap top-k by default, the k-d tree over unit vectors is selectable (`ml.similarity_method`). New `scout similar PLAYER_ID`. Dependency: numpy (BSD) declared explicitly (already pulled in by pandas) for `scripts/bench_knn.py`.
- 2026-10-04: Recommendations (PRD §8.9): a candidate's current club is the club of their latest current-season FPL match; effective minutes (blended) drive both the min-minutes filter and Reliability. A budget filter excludes players with no Transfermarkt estimated market value (counted as "no market value") rather than assuming they are cheap. Market value precedence is config (`recommend.market_value_precedence`: override, live, stale datasets snapshot). Candidates failing the upgrade gate (sideways / insufficient data) are hidden by default and counted under "sideways move"; every exclusion is counted by reason in `Shortlist.excluded`. Ties in FitScore keep profile order (player id) via the stable heap top-k.
- 2026-10-03: StyleFit team style vector = possession share (FotMob), PPDA (Understat) and deep completions per 90 per possession share (directness proxy), configured under `style_features` in `kpis.yaml`. Each is a season/blended rate like the team KPIs, then z-scored across this season's clubs (population sd) so possession (0-1) and PPDA (~5-20) weigh equally in the cosine. Features without spread or with fewer than two clubs are dropped.
- 2026-10-03: FitScore details (PRD §8.9) not fixed by the PRD: NeedFill weights each deficient KPI by group weight x gap (bigger shortfalls count more) and falls back to the group weights when the club trails on nothing; Reliability = 0.6 x minutes volume (effective minutes / 2500, capped) + 0.4 x availability (FPL chance of playing, else a per-status value); StyleFit maps cosine [-1, 1] to [0, 100] and needs at least two shared dimensions; AgeProfile loses 15 points per year outside the peak window. Missing components are dropped and the weights renormalised. Upgrade gate outcomes: upgrade / sideways / no_incumbent / insufficient_data. All tunables in `config/fit_weights.yaml`.
- 2026-10-03: Owner now runs sessions from Claude Code on the web chats instead of hourly routines. The chat harness assigns a session branch (e.g. `claude/dazzling-carson-knix23`); work still lands on `main` (CLAUDE.md locked decision, and commits only count on the contribution graph once they're on the default branch), and the session branch is kept pointing at the same commit. Commits stay authored as Yengnong Xiong.
- 2026-10-03: Team-level needs (PRD §8.8 step 7): team KPIs come from Understat `fact_team_match` via `db/sql/team_season.sql` (per-column totals and match counts, so a missing value counts in neither). Counting stats are per 90; PPDA / PPDA allowed are the mean of per-match ratios (season totals of passes and defensive actions aren't in the source). Blended mode reuses `features/blend.py` with team minutes (matches with data x 90), the same λ and previous-season cap as players. League percentiles use PERCENT_RANK semantics among this season's clubs; gap = benchmark mean percentile − club percentile; only shortfalls become needs. Team needs are attached to their `responsible_groups` as context and do not change group severity (steps 1-3 stay player-KPI based). `kpis.yaml` team KPIs gained `column` and `aggregate`.
- 2026-10-03: Owner asked to stop the CI-failure emails. Added `.github/workflows/preflight.yml` (workflow_dispatch; applies a gzip+base64 patch to a base SHA, runs ruff/format/mypy/pytest/CLI smoke, reports PASSED/FAILED in the log and always exits 0) plus `scripts/preflight_patch.sh`. Code reaches `main` only after preflight passes; `ci.yml` is unchanged and still strict. CLAUDE.md work loop updated.
- 2026-10-03: Warehouse fact tables are long by source (unique on entity × match × source), so each stored value has exactly one source and fetched_at. Initial Alembic migration is hand-written, and a test checks it against the models with `compare_metadata`. Dependencies: sqlalchemy, alembic (MIT); rapidfuzz (MIT) for the Levenshtein reference test and fuzzy matching.
- 2026-10-03: Transfermarkt goes through the owner's self-hosted felipeall/transfermarkt-api (base URL in config, default :8001). TM club ids are resolved by search against club names and aliases (no hardcoded ids). `tm_last_updated` = date of the latest market-value history point; a value with no history point is treated as missing (no receipt). Dependency: unidecode (GPL-2.0+; local, non-distributed use is fine) for name normalisation.
- 2026-10-03: Understat is fetched through soccerdata (PRD §10.1) and snapshotted as CSV. npxG per match = xG minus penalty-shot xG from shot events, because player-match rows carry no npxG. Set-piece = From Corner / Set Piece / Direct Freekick. Third-party fetchers call `PoliteClient.throttle()` so they still respect rate limits and budgets. Dependency: soccerdata (Apache-2.0), with a mypy override because it is untyped.
- 2026-10-03: Dependencies: httpx (HTTP), tenacity (retries with backoff), pandas (DataFrames), pandas-stubs (typing). All BSD/Apache.
- 2026-10-03: Started M1 Python tasks before M0 is fully done, because the remaining M0 items (web scaffold, contract job) are blocked on npm egress. Resume M0-04/05/06 first once npm is reachable.
- 2026-10-03: `config/kpis.yaml` defines each KPI once under `kpis:` and position groups reference KPI ids with weights (PRD §8.7 shape, deduplicated). Validated: weights sum to 1, proxies need `proxy_for`.
- 2026-10-03: Dependencies added: typer (CLI), pydantic + pydantic-settings (config/API models), PyYAML (config), fastapi + uvicorn (API, M7), pytest/pytest-cov/ruff/mypy/types-PyYAML/httpx (dev quality and TestClient). All MIT/BSD/Apache.
- 2026-10-03: Commits are authored as Yengnong Xiong (GitHub noreply email) per owner request; Claude stays as Co-Authored-By. Set in CLAUDE.md session protocol step 4.

## Session log (keep the last 15 entries; summarize older ones in one line)
- 20261003T2032Z-df3b (20:32-21:07 UTC): Finished M3-05 (player_season_features materialised by `scout build`) and M4-01 to M4-04 (benchmark clubs, group scores and gaps, weak links, role scores, risk flags, `scout diagnose` with ranked needs and evidence receipts). Process change after the owner reported CI failure emails: added the always-green `Preflight` workflow (workflow_dispatch + gzip/base64 patch via scripts/preflight_patch.sh); every code push this session passed it first, so main's CI was never red. Next: M4-05 team-level needs. Blocker unchanged: npm/PyPI egress blocked locally (web scaffold waits).
- 20261003T1947Z-9149 (19:47-20:22 UTC): Finished M1 (Understat, FotMob, Transfermarkt live + datasets fallback + overrides, StatsBomb, `scout ingest` runner) and M2 (union-find, Levenshtein, SQLAlchemy models + Alembic 0001, pandera validation, entity resolution, dimension/fact loaders, vaastav history, `scout build`, `scout doctor`), plus M3-01 to M3-04. Lessons: pandas 3 turns missing strings into NaN (assert with pd.isna); pandas-stubs rejects tuple-unpacking groupby keys (use records); SQLAlchemy text() binds ':name' even inside SQL comments. Blocker unchanged: PyPI/npm egress blocked, so CI is the check (main green at f6aa1b6). Next: M3-05 materialise player_season_features (design notes in the queue).
- 20261003T1917Z-2292 (19:17-19:42 UTC): First session. Created PROGRESS; applied ADR-0001 to the PRD (v1.1); Python skeleton (uv/pyproject, validated YAML config, Typer CLI, error hierarchy, network-guard conftest); FastAPI `/health` + error schema + `export-openapi`; CI python job; DSA token bucket + LRU cache; ingest base (snapshot store, polite client, SourceAdapter); FPL and vaastav adapters with synthetic fixtures. Commits now authored as the owner (CLAUDE.md step 4). Blocker: PyPI/npm egress blocked, so local checks were partial and GitHub Actions was the check (2 red pushes, each fixed within minutes; main is green at fa36d17). Next: M1-05 Understat adapter (or M0-04 web scaffold first if npm is reachable).
