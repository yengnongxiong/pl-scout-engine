# Progress
Status: IN_PROGRESS            <!-- IN_PROGRESS or COMPLETE -->
Active session: 20261003T1947Z-9149 started 2026-10-03T19:47:47Z
Current milestone: M2 (M0 web items blocked on npm)

## Plan for this session
- M1-05 Understat adapter (soccerdata-backed fetch, CSV snapshots, schema-validated parse)
- M1-06 FotMob possession adapter

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
- [ ] M2-05 `db/load.py` loaders (dims/facts, idempotent upserts) + `source_snapshot` freshness rows
- [ ] M2-06 `scout build` raw → validated → warehouse with `--allow-invalid` (logged); fixture end-to-end integration test; a validation failure stops the build
- [ ] M2-07 `scout doctor`: freshness, coverage, validation status, missing FPL fields

## Done
- M0-01, M0-02, M0-03 (2026-10-03); Python halves of M0-05/M0-06.
- M1-01 to M1-04 (2026-10-03).

## Blocked
- **Package registries blocked in the cloud sandbox** (2026-10-03): pypi.org and registry.npmjs.org return `403 host_not_allowed` from the egress proxy, so `uv sync` / `npm ci` can't run. Python checks ran locally against preinstalled packages (ruff, pytest and mypy all pass apart from the missing typer/types-PyYAML imports). GitHub Actions CI is the authoritative check. M0-04/M0-05 (web scaffold, `package-lock.json`, FastAPI + OpenAPI) need npm/PyPI and wait until the owner allows those hosts. `uv.lock` isn't committed yet for the same reason; generate it once PyPI is reachable.

## Questions for Yengnong (non-blocking; default chosen)
- `ingest.base_urls.transfermarkt_datasets` defaults to the dataset's public R2 export URL. I couldn't verify it from the sandbox; please confirm or correct it in `config/settings.yaml`. Default: use it as is; a failed fetch just means no stale fallback.
- Please run the self-hosted `felipeall/transfermarkt-api` on :8001 (or change `ingest.base_urls.transfermarkt`) before `scout ingest --source transfermarkt`.
- Please allow `pypi.org`, `files.pythonhosted.org` and `registry.npmjs.org` (or the Trusted network level) in the routine's environment. Default until then: Python work verified via CI, web work paused.

## Decisions log (minor)
- 2026-10-03: Warehouse fact tables are long by source (unique on entity × match × source), so each stored value has exactly one source and fetched_at. Initial Alembic migration is hand-written, and a test checks it against the models with `compare_metadata`. Dependencies: sqlalchemy, alembic (MIT); rapidfuzz (MIT) for the Levenshtein reference test and fuzzy matching.
- 2026-10-03: Transfermarkt goes through the owner's self-hosted felipeall/transfermarkt-api (base URL in config, default :8001). TM club ids are resolved by search against club names and aliases (no hardcoded ids). `tm_last_updated` = date of the latest market-value history point; a value with no history point is treated as missing (no receipt). Dependency: unidecode (GPL-2.0+; local, non-distributed use is fine) for name normalisation.
- 2026-10-03: Understat is fetched through soccerdata (PRD §10.1) and snapshotted as CSV. npxG per match = xG minus penalty-shot xG from shot events, because player-match rows carry no npxG. Set-piece = From Corner / Set Piece / Direct Freekick. Third-party fetchers call `PoliteClient.throttle()` so they still respect rate limits and budgets. Dependency: soccerdata (Apache-2.0), with a mypy override because it is untyped.
- 2026-10-03: Dependencies: httpx (HTTP), tenacity (retries with backoff), pandas (DataFrames), pandas-stubs (typing). All BSD/Apache.
- 2026-10-03: Started M1 Python tasks before M0 is fully done, because the remaining M0 items (web scaffold, contract job) are blocked on npm egress. Resume M0-04/05/06 first once npm is reachable.
- 2026-10-03: `config/kpis.yaml` defines each KPI once under `kpis:` and position groups reference KPI ids with weights (PRD §8.7 shape, deduplicated). Validated: weights sum to 1, proxies need `proxy_for`.
- 2026-10-03: Dependencies added: typer (CLI), pydantic + pydantic-settings (config/API models), PyYAML (config), fastapi + uvicorn (API, M7), pytest/pytest-cov/ruff/mypy/types-PyYAML/httpx (dev quality and TestClient). All MIT/BSD/Apache.
- 2026-10-03: Commits are authored as Yengnong Xiong (GitHub noreply email) per owner request; Claude stays as Co-Authored-By. Set in CLAUDE.md session protocol step 4.

## Session log (keep the last 15 entries; summarize older ones in one line)
- 20261003T1917Z-2292 (19:17-19:42 UTC): First session. Created PROGRESS; applied ADR-0001 to the PRD (v1.1); Python skeleton (uv/pyproject, validated YAML config, Typer CLI, error hierarchy, network-guard conftest); FastAPI `/health` + error schema + `export-openapi`; CI python job; DSA token bucket + LRU cache; ingest base (snapshot store, polite client, SourceAdapter); FPL and vaastav adapters with synthetic fixtures. Commits now authored as the owner (CLAUDE.md step 4). Blocker: PyPI/npm egress blocked, so local checks were partial and GitHub Actions was the check (2 red pushes, each fixed within minutes; main is green at fa36d17). Next: M1-05 Understat adapter (or M0-04 web scaffold first if npm is reachable).
