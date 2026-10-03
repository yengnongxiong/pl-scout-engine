# CLAUDE.md

Guidance for Claude Code in this repository. `PRD.md` is the source of truth for scope, requirements, methodology and milestones. Accepted ADRs in `docs/decisions/` override the PRD where they conflict. This file covers how to work.

## Project in one paragraph
PL Scout Engine is a local, explainable recruitment dashboard for the Premier League. Pick a club → the engine diagnoses squad weaknesses from this season's match data (blended with last season while samples are small) → it recommends PL players who fix them, with a transparent fit score, Transfermarkt estimated market value (with as-of date) and an auto-generated scouting report. Python data/ML/API back end, React + TypeScript front end. Free data only, no paid AI APIs, not publicly deployed. Product principle: **no number without a receipt.**

## Autonomous mode — read this first
This repo is built by unattended Claude Code sessions started by an hourly scheduled routine. No human is watching.
- Never ask for permission, confirmation or clarification, and never end a session with a question. Make the most reasonable decision, record it (ADR for significant ones, otherwise a line in `docs/PROGRESS.md`), and continue.
- Questions for the owner go under "Questions for Yengnong (non-blocking)" in `docs/PROGRESS.md`, each with the default you chose. Never wait for an answer.
- A session can be cut off at any moment (usage limits). Push after every completed task so at most one small task is lost.

### Locked decisions (don't revisit)
- Front end: React + TypeScript SPA in `web/` (ADR-0001). No Streamlit.
- M0 scaffolds both the Python package and `web/` so CI covers both stacks from day one; M8 builds the real pages.
- Default benchmark: top 6 of last season's table, with toggles for league / top 4 / custom.
- Candidate pool: Premier League only. Stretch S1 (event data) and S6 (top-5 leagues) need the owner's go-ahead: do not start them.
- Goalkeepers: not in the MVP; they're stretch S2.
- Database: SQLite by default, Postgres-compatible SQL.
- Reports: template engine by default; Ollama is optional and must never be required.
- Branching: work on `main` and push directly to `main`. Never create other branches, never force-push, never rewrite history.

### Session protocol (follow exactly, every session)
1. **Sync:** `git checkout main && git pull --rebase`.
2. **Check whether to run:** read `docs/PROGRESS.md`. If it doesn't exist, this is the first session: skip to step 3 and create it from the template below.
   - If `Status: COMPLETE`, end the session immediately without changes.
   - If `Active session:` holds a timestamp less than 75 minutes old, another session is running: end immediately without changes.
3. **Claim the session:** generate a session ID (`date -u +%Y%m%dT%H%MZ` plus 4 random hex characters). Set `Active session: <ID> started <UTC ISO time>` and write a short "Plan for this session" (next 1–3 tasks) in `docs/PROGRESS.md`. Commit `docs(progress): start session <ID>` and push. If the push is rejected, `git pull --rebase` and go back to step 2.
4. **Set up the toolchain:**
   - If `uv` is missing, `pip install uv` (add `--break-system-packages` if pip refuses).
   - `uv sync --all-extras`
   - `npm ci` inside `web/` once it exists.
5. **Work loop:**
   - Take the first unchecked task in the "Task queue." If the queue is empty, break the current milestone (PRD §16) into tasks of roughly 20–40 minutes each, write them to the queue, and commit.
   - Implement it, run all checks (see Definition of done), commit with a conventional message, then `git pull --rebase` and push.
   - Before every push, confirm `Active session:` in `docs/PROGRESS.md` still shows **your** ID. If it doesn't, another session has taken over: discard your local changes and end the session.
6. **Timebox:** measure elapsed time from your start timestamp with `date -u`. After 40 minutes, don't start a new task. Be fully wrapped up by 55 minutes.
7. **Wrap up:**
   - Set `Active session: none`.
   - Add a session-log entry (ID, tasks done, next task, blockers).
   - Commit `docs(progress): end session <ID>`, push, and end the session.

### Guardrails
- Commit only green states: tests, lint and type checks pass. If a task can't be finished, commit any self-contained passing part, write exact next steps in the task's note, and leave it unchecked.
- If the same task fails in 2 sessions, move it to "Blocked" with what you tried and why, then continue with the next independent task. Never loop on one problem.
- Never weaken or delete tests, lower coverage thresholds, add blanket `# type: ignore` / `eslint-disable`, or skip CI checks to get green.
- Order of work: M0 → M9. Then stretch in this order: S7, S2, S4, S5, S3. Then set `Status: COMPLETE`.
- **M0 includes applying ADR-0001 to `PRD.md`:** make the listed edits, bump the PRD to v1.1, and add a changelog line.
- The final deliverable must include `uv run scout demo`: one command that runs ingest (if no data), build and train, then starts the API and the web app. The README must explain it.

### `docs/PROGRESS.md` format
```markdown
# Progress
Status: IN_PROGRESS            <!-- IN_PROGRESS or COMPLETE -->
Active session: none           <!-- or "<ID> started <UTC ISO>" -->
Current milestone: M0

## Plan for this session
## Task queue (current milestone)
- [ ] M0-01 Short task title — acceptance check
## Done
## Blocked
## Questions for Yengnong (non-blocking; default chosen)
## Decisions log (minor)
## Session log (keep the last 15 entries; summarize older ones in one line)
```

## Environment (Claude Code cloud sessions)
- Network may be the default **Trusted** level: PyPI, npm and GitHub reachable, most other sites blocked. The owner may allow `fantasy.premierleague.com`, `understat.com`, `www.fotmob.com` and Transfermarkt domains.
- Live requests are allowed only to verify adapters or refresh small trimmed fixtures:
  - Per-session caps: FPL ≤ 50 requests; Understat and FotMob ≤ 20 each; Transfermarkt ≤ 10, spaced ≥ 3 s apart.
  - If a host is blocked (`403 host_not_allowed`, anti-bot page), note it once in `docs/PROGRESS.md` and continue with fixtures. Never retry in a loop or try to work around the block.
- Tests always use local fixtures. Full ingestion is for the owner's machine via `scout demo` / `scout ingest`.
- Ollama isn't available in the sandbox. Everything must work with `REPORT_ENGINE=template`.

## Commands
```bash
# Python back end
uv sync --all-extras
uv run scout --help
uv run scout ingest --source all     # live data (owner's machine; small samples only in cloud)
uv run scout build                   # raw → validated → warehouse → features
uv run scout train                   # ML models + docs/EVALUATION.md
uv run scout doctor                  # freshness, coverage, validation status
uv run scout api                     # FastAPI on http://localhost:8000 (docs at /docs)
uv run scout export-openapi          # writes web/openapi.json
uv run scout demo                    # owner's one command: ingest if needed → build → train → API + web
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src

# React + TypeScript front end (run inside web/)
npm ci
npm run gen:api                      # regenerate TS types from openapi.json
npm run dev                          # Vite on http://localhost:5173, proxies /api → :8000
npm run lint && npm run typecheck && npm run test && npm run build
```

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
│   └── api/       main.py · routers/ · schemas.py · deps.py
├── web/           React + TypeScript (Vite)
│   ├── openapi.json   (generated by `scout export-openapi`, committed)
│   ├── src/       api/ (generated types + client) · pages/ · components/ · hooks/ · lib/ · test/
│   └── package.json · vite.config.ts · tsconfig.json · eslint.config.js
└── tests/         unit/ · integration/ · fixtures/ · conftest.py
```

## Architecture rules
- Back-end layer order: `ingest → transform → db → features → engines/ml → reports → api`. A layer never imports from a layer to its right.
- `web/` talks to the back end only over HTTP, through the client generated from `web/openapi.json`. No hand-written duplicate API types.
- After any API change: run `scout export-openapi` and `npm run gen:api`, and commit both outputs. CI fails on drift.
- Each source is one adapter implementing `SourceAdapter`: `fetch()` writes a raw snapshot to disk, `parse()` returns a validated DataFrame.
- The API and front end read the warehouse only. No external network calls at request time.
- Thresholds, weights, rate limits and mappings go in `config/*.yaml` or env (pydantic-settings). No magic numbers.
- Analytical SQL lives in `db/sql/*.sql` (CTEs, window functions), portable across SQLite and Postgres, and each query has a pandas twin in tests.
- Metric math is pure functions. ML is seeded; saved models include a metadata JSON (data window, features, metrics, git SHA).

## Data integrity rules (non-negotiable)
1. Never fabricate, hardcode, or silently impute stats, players, clubs or market values. Synthetic data only in `tests/fixtures/` and front-end MSW handlers, with `synthetic` in the file name.
2. Missing data is `None`/`NULL`/`null` and renders as "Not available." Never default missing values to 0.
3. Every stored metric row carries `source` and `fetched_at`. Market values also carry Transfermarkt's own last-updated date. Every number in the UI or a report must be traceable to these.
4. Proxy metrics are flagged `is_proxy: true` in `config/kpis.yaml` and badged in the UI (PRD §7.2).
5. Do not use FBref advanced stats (removed January 2026).
6. FPL `id` changes every season; join and persist on FPL `code`.
7. Never hardcode season strings; derive the current season from FPL `bootstrap-static` events.
8. Rates are per 90, never per match. Percentiles only among players meeting the minutes threshold; always expose `n_peers` and minutes.
9. Defensive volume KPIs are possession-adjusted when possession exists; otherwise flagged "unadjusted."
10. Say "Transfermarkt estimated market value," never "price" or "fee."
11. Scraping etiquette:
    - Rate limits come from config; cache with a TTL; send a descriptive User-Agent.
    - Treat empty or interstitial pages as failures.
    - Personal, non-commercial use only. Never commit `data/raw/` or scraped datasets; fixtures are small trimmed samples.
12. Validation failures stop `scout build` (only an explicit, logged `--allow-invalid` overrides).

## DSA modules (`src/scout/dsa/`)
Hand-implemented, each with a docstring stating time/space complexity, a test against a stdlib/library reference, and a real call site:
- `heap_topk`: O(n log k) top-k for shortlists and similarity.
- `kdtree`: nearest neighbours, plus `scripts/bench_knn.py` showing why brute force wins at ~600 players.
- `lru_cache`: hash map + doubly linked list for API hot endpoints.
- `token_bucket`: ingestion rate limiting.
- `union_find`: merges cross-source player records during entity resolution.
- `trie`: prefix autocomplete in `/players/search` and `/teams/search`.
- `levenshtein`: DP edit distance; tests show it agrees with `rapidfuzz`.

## Code style
**Python**
- Python 3.12, full type hints, mypy clean on `src/`.
- ruff for lint + format, line length 100.
- Google-style docstrings. Explain the *why* behind statistical choices with a PRD section reference.
- Structured `logging`; no `print` outside the CLI.
- Custom exceptions in `errors.py`, mapped by the API to one error schema.

**TypeScript**
- `strict: true`; no `any` (use `unknown` and narrow).
- Function components and hooks. Server state only through TanStack Query hooks in `src/hooks/`.
- Filters, season mode and benchmark live in URL query params.
- Tailwind for styling. Small, accessible components (keyboard support, labels, AA contrast, colour never the only signal).
- All number/currency/date formatting goes through `src/lib/format.ts`.
- Every page handles loading, empty and error states.

**Both**
- Conventional commits; small, focused commits.
- Free/open-source dependencies only, each justified in one line in `docs/PROGRESS.md` or an ADR.

## Testing and CI
- Python: pytest, with unit tests in `tests/unit/` and fixture-based end-to-end builds in `tests/integration/`.
  - A `conftest.py` guard blocks all network access.
  - Hand-calculated tests for every formula.
  - Contract tests per adapter, including a "schema changed" failure test.
  - Golden-file tests for reports; the grounding validator must reject an injected fake number.
  - Coverage ≥ 80% on `features`, `engines`, `ml`, `reports`, `dsa`.
- Web: Vitest + React Testing Library + MSW (no real network). Each page is tested in loading, empty, error and success states.
- `.github/workflows/ci.yml` has three jobs:
  - `python`: ruff, mypy, pytest with coverage.
  - `web`: npm ci, lint, typecheck, test, build.
  - `contract`: export OpenAPI, regenerate types, `git diff --exit-code`.
- Run the same checks locally before every push.

## Known gotchas
- FPL `element-summary` history empties after a season ends, so past seasons come from the vaastav archive.
- FPL fields are undocumented. Validate the schema every run and surface missing fields in `scout doctor`.
- Names differ across sources. Use `unidecode`, block by club, fuzzy match, confirm with date of birth, fall back to `data/overrides/player_overrides.csv`, and log unresolved records to `entity_map_review`.
- Transfermarkt anti-bot pages can return HTTP 200/202 with no data. Validate parsed fields.
- `transfermarkt-datasets` updates are paused (valuations end June 2026): use it for history/training and as a labelled-stale fallback only.
- For players who moved clubs, club-level aggregates use only minutes played for that club.
- Early season: always show minutes; rely on blending + shrinkage (PRD §8.2–8.3).
- Vite dev proxy forwards `/api` to `:8000`; FastAPI CORS allows only `http://localhost:5173`.

## Definition of done (any task)
- Python and web checks pass: tests, lint, types, and build where relevant.
- OpenAPI and generated types are in sync.
- Config is used instead of constants.
- No new number appears without a source and as-of date.
- `docs/PROGRESS.md` is updated.
- Changes are pushed to `main`.