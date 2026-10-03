# CLAUDE.md

Guidance for Claude Code in this repository. **`PRD.md` is the source of truth** for scope, requirements, methodology and milestones. This file covers how to work.

## Project in one paragraph
PL Scout Engine is a local, explainable recruitment dashboard for the Premier League. Pick a club → the engine diagnoses squad weaknesses from this season's match data (blended with last season while samples are small) → it recommends PL players who fix them, with a transparent fit score, Transfermarkt estimated market value (with as-of date) and an auto-generated scouting report. Free data only, no paid AI APIs, not publicly deployed. Product principle: **no number without a receipt.**

## Start of every session
1. Read `docs/PROGRESS.md` (create it in M0 if missing).
2. Read the PRD section(s) for the current milestone (PRD §16). Work on one milestone at a time; don't start the next until the current one's acceptance criteria are met.
3. Run `uv run pytest -q` to confirm a green baseline before changing anything.

## End of every session
1. Tests, ruff and mypy pass.
2. Update `docs/PROGRESS.md`: done, next, blockers, and a "Questions for Yengnong" section.
3. Record significant decisions as ADRs in `docs/decisions/NNNN-title.md` (context → decision → consequences, ≤ 1 page).

## Environment (Claude Code on the web)
- You are probably in a cloud sandbox with **Trusted** network access. PyPI and GitHub are reachable; `fantasy.premierleague.com`, `understat.com`, FotMob and Transfermarkt probably are **not**. Do not try to work around network blocks.
- Develop and test against fixtures in `tests/fixtures/`. Live ingestion (`scout ingest`) is run by the human on their own machine.
- GitHub-hosted data (StatsBomb open data, the vaastav FPL archive, transfermarkt-datasets) may be reachable for exploration, but tests must still use local fixtures.
- Ollama is not available in the sandbox. The report pipeline must work fully with `REPORT_ENGINE=template`.

## Commands
```bash
uv sync --all-extras                 # install
uv run scout --help                  # CLI entry point
uv run scout ingest --source all     # fetch raw data (LOCAL machine only; needs network)
uv run scout build                   # raw → validated → warehouse → features
uv run scout train                   # ML models + docs/EVALUATION.md
uv run scout doctor                  # freshness, coverage, validation status
uv run scout api                     # FastAPI on http://localhost:8000 (docs at /docs)
uv run scout ui                      # Streamlit on http://localhost:8501
uv run pytest -q                     # tests (no network)
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```
A `Makefile` mirrors these, but the Typer CLI is the cross-platform primary interface.

## Repository layout
```text
pl-scout-engine/
├── CLAUDE.md  PRD.md  README.md  pyproject.toml  Makefile  .env.example
├── .github/workflows/ci.yml
├── config/        settings.yaml · kpis.yaml · fit_weights.yaml · positions.yaml · team_aliases.yaml
├── data/          (gitignored) raw/ · staging/ · warehouse/ · models/
│   └── overrides/ player_overrides.csv · market_value_overrides.csv   (committed)
├── docs/          PROGRESS.md · EVALUATION.md · METHODOLOGY.md · decisions/
├── scripts/       bench_knn.py and other one-off utilities
├── src/scout/
│   ├── config.py  errors.py  cli.py
│   ├── ingest/    base.py (SourceAdapter, cache) · fpl.py · understat.py · fotmob.py · transfermarkt.py · history.py · statsbomb.py
│   ├── transform/ clean.py · entity_resolution.py · validate.py
│   ├── db/        models.py · session.py · load.py · migrations/ · sql/*.sql
│   ├── features/  per90.py · blend.py · shrinkage.py · possession.py · percentiles.py
│   ├── engines/   diagnosis.py · recommend.py · fit.py
│   ├── ml/        roles.py · similarity.py · value_model.py
│   ├── reports/   facts.py · render.py · templates/ · llm.py · grounding.py
│   ├── dsa/       heap_topk.py · kdtree.py · lru_cache.py · token_bucket.py · union_find.py · trie.py · levenshtein.py
│   ├── api/       main.py · routers/ · schemas.py · deps.py
│   └── ui/        app.py · pages/ · components/ · api_client.py
└── tests/         unit/ · integration/ · fixtures/ · conftest.py
```

## Architecture rules
- Layer order: `ingest → transform → db → features → engines/ml → reports → api → ui`. A layer never imports from a layer to its right. `ui/` talks to the API over HTTP via `api_client.py` only.
- Each source is one adapter implementing `SourceAdapter`: `fetch()` writes a raw snapshot to disk, `parse()` returns a validated DataFrame. Adding or removing a source must not touch other layers beyond `transform/`.
- The API and UI read the warehouse only. No external network calls at request time.
- Thresholds, weights, rate limits and mappings go in `config/*.yaml` or env (pydantic-settings). No magic numbers in code.
- Analytical SQL lives in `db/sql/*.sql` (CTEs, window functions) and must be portable across SQLite and Postgres. Every SQL query that produces displayed numbers has a pandas twin in tests.
- Metric math is pure functions. ML is seeded; saved models include a metadata JSON (data window, features, metrics, git SHA).

## Data integrity rules (non-negotiable)
1. Never fabricate, hardcode, or silently impute stats, players, clubs or market values. Synthetic data is allowed only in `tests/fixtures/`, with `synthetic` in the filename.
2. Missing data is `None`/`NULL` and renders as "Not available." Never default missing values to 0.
3. Every stored metric row carries `source` and `fetched_at`. Market values also carry Transfermarkt's own last-updated date. Every number in the UI or a report must be traceable to these.
4. Proxy metrics are flagged `is_proxy: true` in `config/kpis.yaml` and badged in the UI. Player-level "pressing" and Tier-1 "progression" are proxies (PRD §7.2).
5. Do **not** use FBref advanced stats (removed January 2026). FBref is for history and basic stats only.
6. FPL `id` changes every season. Join and persist on FPL `code`.
7. Never hardcode season strings. Derive the current season from FPL `bootstrap-static` events.
8. Rates are per 90 minutes, never per match. Compute percentiles only among players meeting the minutes threshold, and always expose `n_peers` and minutes.
9. Possession-adjust defensive volume KPIs when possession data exists; otherwise flag them "unadjusted."
10. Call it "Transfermarkt estimated market value," never "price" or "fee."
11. Scraping etiquette:
    - Per-source rate limits come from config (Transfermarkt ≤ 1 request / 3 s, no concurrency).
    - Cache with a TTL and send a descriptive User-Agent.
    - Treat empty or interstitial pages as failures.
    - Personal, non-commercial use only. Never commit `data/raw/` or scraped datasets.
12. Validation failures stop `scout build`. The only override is an explicit, logged `--allow-invalid` flag.

## DSA modules (`src/scout/dsa/`)
Implement each by hand, with a docstring stating time/space complexity, a test comparing against a stdlib/library reference, and at least one real call site:
- `heap_topk`: top-k shortlist/similarity selection, O(n log k). Used in `engines/recommend.py` and `ml/similarity.py`.
- `kdtree`: nearest neighbours. `scripts/bench_knn.py` compares it against brute force and documents why brute force is used at ~600 players.
- `lru_cache`: hash map + doubly linked list, O(1) get/put. Used for API hot endpoints.
- `token_bucket`: rate limiter for ingestion adapters.
- `union_find`: merges cross-source player records into canonical players during entity resolution.
- `trie`: prefix autocomplete for player/club search.
- `levenshtein`: DP edit distance. Production matching may use `rapidfuzz`, but tests must show both agree.

## Code style
- Python 3.12, full type hints, mypy clean on `src/`.
- ruff for lint + format, line length 100.
- Google-style docstrings on public functions. For any statistical choice, explain *why* in one or two sentences and cite the PRD section.
- Structured `logging`; no `print` outside the CLI.
- Custom exceptions in `errors.py`; the API maps them to one consistent error schema.
- Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`); small, focused commits.
- Free/open-source dependencies only. Any new one gets a one-line justification in `docs/PROGRESS.md` or an ADR.

## Testing
- pytest. Unit tests go in `tests/unit/`; end-to-end builds from fixtures go in `tests/integration/`.
- **No network in tests.** A `conftest.py` guard fails any socket connection.
- Every formula (per-90, blend, shrinkage, PAdj, percentiles, fit score) has a hand-calculated test case.
- Adapters have contract tests against trimmed recorded payloads, including a "schema changed" test that must fail loudly.
- Report templates have golden-file tests. The grounding validator has a test that injects a fabricated number and asserts rejection.
- Coverage ≥ 80% on `features`, `engines`, `ml`, `reports` and `dsa`. CI must be green before a milestone is marked done.

## Known gotchas
- FPL `element-summary` history empties after a season ends, so past seasons come from the vaastav archive.
- FPL fields are undocumented. Validate the payload schema every run and surface missing fields in `scout doctor`.
- Names differ across sources (accents, nicknames, mononyms). Normalise with `unidecode`, block by club, fuzzy match, and confirm with date of birth. Fall back to `data/overrides/player_overrides.csv` and log unresolved records to `entity_map_review`.
- Transfermarkt anti-bot responses can be HTTP 200/202 with no data. Validate parsed fields.
- `transfermarkt-datasets` updates are paused (valuations end June 2026). Use it only for history/training and as a labelled-stale fallback.
- For players who moved clubs, club-level aggregates use only minutes played for that club.
- Early in the season, always show minutes and rely on blending + shrinkage (PRD §8.2–8.3).

## Definition of done (any task)
- Code, tests, types and lint pass.
- Config is used instead of constants.
- `docs/PROGRESS.md` is updated.
- No new number appears without a source and as-of date.
- The milestone's PRD acceptance criteria are met.

## When unsure
Choose the more conservative, transparent option. Write the question under "Questions for Yengnong" in `docs/PROGRESS.md`, and continue with work that doesn't depend on the answer.