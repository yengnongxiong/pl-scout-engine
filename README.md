<div align="center">

# ⚽ PL Scout Engine

**Moneyball for the Premier League.** Find where a squad is weakest, then the players who fix it, with the evidence behind every number.

[![CI](https://github.com/yengnongxiong/pl-scout-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/yengnongxiong/pl-scout-engine/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![React + TypeScript](https://img.shields.io/badge/UI-React%20%2B%20TypeScript-3178C6?logo=typescript&logoColor=white)
![SQL](https://img.shields.io/badge/Data-SQLite%20%7C%20Postgres-336791?logo=postgresql&logoColor=white)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[What it does](#what-it-does) · [See it in action](#see-it-in-action) · [Try it](#try-it-yourself) · [How it works](#how-it-works) · [Under the hood](#under-the-hood-for-engineers) · [Docs](#project-documents) · [How it was built](#how-it-was-built)

</div>

![Club diagnosis for Man Utd: need severity by position group, with the striker group as the biggest shortfall](docs/screenshots/diagnosis.png)

## What it does

Clubs don't recruit by asking "who is the best player?". They ask **"where is our squad weak, and who fixes it?"** PL Scout Engine answers that question with data, the way the Oakland A's did in *Moneyball*:

| Step | What happens | Example (Man Utd, data as of 11 Oct 2026) |
|---|---|---|
| **1. Diagnose** | Pick a club. The engine compares every position group with a benchmark (by default, last season's top six) and ranks where the squad falls short. | Strikers are the biggest need: Man Utd rank in the 15th percentile for chance quality (non-penalty xG) against the benchmark's 57th. |
| **2. Recommend** | For each need, it ranks Premier League players who would fix it with a 0–100 **FitScore** you can open up and inspect, next to their market value. | Erling Haaland (91.9), Igor Thiago (80.0), Thierno Barry (76.1), each shown as a clear upgrade on the current starter. |
| **3. Explain** | It writes a plain-English **scouting report** for any player, and checks that every number in it really exists in the data before showing it. | "Strong fit. Erling Haaland addresses the ST need at Man Utd and clears the upgrade gate." |

It runs on **free public data**, on your own computer, with **no paid AI**.

### Why you can trust the numbers

The rule behind every screen is **"no number without a receipt"**:

- **Every number shows where it came from and when** (for example "Understat · as of 11 Oct 2026").
- **Missing data says "Not available"**, never a silent zero.
- **Estimates are labelled**: stand-in metrics carry a *proxy* badge, old market values a *stale* badge, and small samples a warning.
- **The models are tested on a season they never saw**, and the results are published in [`docs/EVALUATION.md`](docs/EVALUATION.md).

## See it in action

*All screenshots come from a local run on live 2026-27 data.*

| 1. Ranked candidates for a need, with the FitScore breakdown open | 2. The Moneyball view: market estimate vs what the stats imply |
|---|---|
| ![Shortlist of strikers for Man Utd with Erling Haaland's FitScore breakdown](docs/screenshots/shortlist.png) | ![Scatter plot of Transfermarkt estimated market value against stats-implied value](docs/screenshots/moneyball.png) Players **above the diagonal** look under-priced by the market. |

| 3. A player page: percentiles against position peers, value, age curve | 4. An auto-written scouting report, ready to copy or download as PDF |
|---|---|
| ![Player page for Erling Haaland](docs/screenshots/player.png) | ![Scouting report for Erling Haaland against Man Utd's striker need](docs/screenshots/report.png) |

<details>
<summary><b>More screens:</b> compare, backtest, methodology and data freshness</summary>

| Compare a candidate with the current starter | Backtest: did past needs match real signings? |
|---|---|
| ![Compare page](docs/screenshots/compare.png) | ![Backtest page](docs/screenshots/backtest.png) |

![Methodology and data page showing source freshness and KPI definitions](docs/screenshots/methodology.png)

</details>

## Try it yourself

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you), [Node.js](https://nodejs.org/) 22 or newer, and an internet connection for the first data download.

```bash
git clone https://github.com/yengnongxiong/pl-scout-engine.git
cd pl-scout-engine
uv sync --all-extras
uv run scout demo
```

Then open **http://localhost:5173**. That one command downloads the data politely (about 20 minutes the first time), checks it, builds the database, trains the models, and starts the dashboard. Later runs start in seconds with `uv run scout demo --skip-build`; add `--refresh` to fetch new match data.

<details>
<summary><b>Optional extras</b>: current market values, Postgres, a local AI writer</summary>

- **Current Transfermarkt values:** run the free, self-hosted [`felipeall/transfermarkt-api`](https://github.com/felipeall/transfermarkt-api) on port 8001. Without it, values come from a public snapshot that ends in June 2026 and are labelled *stale*.
- **Postgres instead of SQLite:** `docker compose up -d db`, then `export SCOUT_DATABASE_URL=postgresql+psycopg://scout:scout@localhost:5432/scout` before `uv run scout demo`. CI checks that both databases give identical answers.
- **Local AI-written reports:** set `REPORT_ENGINE=ollama` and `SCOUT_OLLAMA_MODEL=<model>` with [Ollama](https://ollama.com) running. A rewrite is only shown if every number and name in it passes the fact checker; otherwise you get the template report.

</details>

## How it works

```mermaid
flowchart LR
  A["1. Collect<br/>free data sources"] --> B["2. Clean & connect<br/>one player across all sources"]
  B --> C["3. Store<br/>SQL database with receipts"]
  C --> D["4. Analyse<br/>needs, fit, machine learning"]
  D --> E["5. Show<br/>dashboard and reports"]
```

1. **Collect.** Match stats come from the official Fantasy Premier League API and [Understat](https://understat.com), team possession from ESPN, and market value estimates from Transfermarkt. Past seasons come from public archives. Downloads are rate-limited, cached and saved untouched, so every build can be replayed.
2. **Clean & connect.** The data is validated, and each player is matched across sources ("Bruno Fernandes" in one is "Bruno Borges Fernandes" in another) using club, name similarity and date of birth.
3. **Store.** Everything lands in a SQL database where each number keeps its source and timestamp.
4. **Analyse.** Stats become fair comparisons: rates per 90 minutes, this season blended with last while samples are small, defensive numbers adjusted for how much of the ball a team has, and percentiles among players in the same position. The engine then scores needs and candidates, and machine-learning models add playing-style groups, similar players, a stats-implied market value and age curves.
5. **Show.** A read-only API serves the React dashboard and the scouting reports. The dashboard never calls an outside website.

<details>
<summary><b>The method in a little more detail</b></summary>

- **Rates** are per 90 minutes, **blended** with last season while this season's sample is small: `(m_cur·r_cur + λ·m_prev·r_prev) / (m_cur + λ·m_prev)`, with last season's minutes capped. They are then **shrunk** toward the position average: `(n·rate + k·prior) / (n + k)`.
- **Defensive volume** is **possession-adjusted** (`× 0.5 / opponent possession`, clipped); without possession data it is flagged "unadjusted".
- **Percentiles** rank players within their position group, among those above a minutes threshold, always with the number of peers.
- **Diagnosis:** minutes-weighted group percentiles against the benchmark; severity = Σ KPI weight × shortfall. It also flags weak links, depth, age and contract risks, and team-level needs.
- **FitScore** = 0.40 NeedFill + 0.25 RoleQuality + 0.15 Reliability + 0.10 StyleFit + 0.10 AgeProfile, plus an **upgrade gate** against the current starter.
- **Machine learning:** Gaussian-mixture role archetypes (k chosen by BIC), cosine similarity, a gradient-boosted **stats-implied value** with a conformally calibrated 80% band, and delta-method age curves.
- **Reports:** a fact sheet, Jinja2 templates, an optional local LLM rewrite, and a **grounding validator** that rejects any number, date or name not in the fact sheet.

The full method is in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) and on the dashboard's Methodology page.

</details>

## Under the hood (for engineers)

| Layer | Built with |
|---|---|
| Data pipeline | Python 3.12, httpx, pandas, pandera, `soccerdata` (Understat), hand-written source adapters |
| Storage | SQLAlchemy 2, Alembic migrations, SQLite by default, Postgres optional, analytical SQL with CTEs and window functions |
| Analytics & ML | scikit-learn (Gaussian mixtures, gradient boosting with quantile loss), NumPy, conformal calibration |
| API | FastAPI, pydantic, an OpenAPI schema exported for the front end |
| Front end | React 19, TypeScript (strict), Vite, TanStack Query and Table, Recharts, Tailwind CSS |
| Quality | pytest, Vitest, Testing Library, MSW, ruff, mypy (strict), ESLint, Prettier, GitHub Actions |

### What it demonstrates

| Skill | Where to look |
|---|---|
| **SQL & data modelling** | Star-schema warehouse, migrations, CTE/window-function queries in [`src/scout/db/sql/`](src/scout/db/sql/), each checked against a pandas twin |
| **APIs** | Consuming several external sources politely; designing a typed REST API in [`src/scout/api/`](src/scout/api/) with a generated TypeScript client |
| **System design** | Medallion layers (raw → validated → warehouse), adapter pattern, batch build vs read-only request path, caching, rate limiting |
| **Data structures & algorithms** | Hand-written heap top-k, k-d tree, LRU cache, token bucket, union-find, trie and Levenshtein distance in [`src/scout/dsa/`](src/scout/dsa/) |
| **Machine learning & statistics** | Time-split evaluation against a baseline, calibrated uncertainty, clustering, similarity search, empirical-Bayes shrinkage |
| **Testing & CI** | About 460 Python and 56 web tests, 94% coverage, network-free tests, Postgres parity tests, and an API-contract check in CI |
| **Product management** | [PRD](PRD.md) with personas, prioritised user stories, success metrics and their results, a risk register, and decision records ([ADRs](docs/decisions/)) |

### Results on live data (11 October 2026)

| Measure | Result |
|---|---|
| Stats-implied value vs a naive baseline (held-out 2025-26 season) | **28% lower error** (median 27.7% vs 40.7% off) |
| Uncertainty band coverage | **80%**, calibrated (the raw quantile models covered only 49%) |
| Players linked across sources (share of minutes) | Understat **99.1%**, Transfermarkt **80.6%** (snapshot predates summer signings) |
| API response time, all 20 clubs, uncached (p95) | **107 ms** diagnosis, **218 ms** shortlist |
| Backtest: top-3 needs vs positions later signed | 49% (a naive baseline scores 73%; clubs sign for many reasons, so this stays exploratory) |

<details>
<summary><b>Command reference</b></summary>

```bash
uv run scout --help
uv run scout ingest --source all        # or fpl, vaastav, understat, espn, transfermarkt, ...
uv run scout build                      # raw → validated → warehouse → features
uv run scout train                      # models + docs/EVALUATION.md
uv run scout doctor                     # freshness, coverage, validation, FPL schema
uv run scout diagnose "Man Utd"         # needs, from the terminal
uv run scout recommend "Man Utd" --need ST --max-value 40
uv run scout report "Erling Haaland" --team "Man Utd" --pdf report.pdf
uv run scout backtest                   # last season's needs vs this season's arrivals
uv run scout api                        # FastAPI on :8000 (docs at /docs)
uv run scout export-openapi             # writes web/openapi.json

make check        # ruff, mypy, pytest with coverage, and the web lint/typecheck/test/build
make contract     # export OpenAPI, regenerate the TypeScript types, fail on drift
```

</details>

<details>
<summary><b>Hand-written data structures and where they are used</b></summary>

| Module | Used for | Complexity |
|---|---|---|
| `heap_topk` | Shortlists and similar players | O(n log k) |
| `kdtree` | Nearest neighbours (benchmarked against brute force in `scripts/bench_knn.py`) | O(log n + k) average query |
| `lru_cache` | Hot API endpoints (hash map + doubly linked list) | O(1) get/put |
| `token_bucket` | Polite download rate limits | O(1) |
| `union_find` | Merging one player's records across sources | ~O(α(n)) |
| `trie` | Club and player search-as-you-type | O(m + r) per prefix |
| `levenshtein` | Fuzzy name matching (checked against rapidfuzz) | O(mn) |

</details>

### Repository map

Each main folder has its own short guide; click through for details.

```text
pl-scout-engine/
├── src/scout/   the engine: collect → clean → store → analyse → serve   (guide: src/scout/README.md)
├── web/         the React + TypeScript dashboard                         (guide: web/README.md)
├── config/      every weight, threshold and mapping, no magic numbers    (guide: config/README.md)
├── tests/       ~460 offline tests on synthetic data                     (guide: tests/README.md)
├── docs/        methodology, evaluation, decisions, build log            (guide: docs/README.md)
├── data/        local data, never committed, plus manual overrides      (guide: data/README.md)
├── scripts/     one-off tools (k-d tree benchmark, CI preflight)
├── PRD.md       the product requirements document
└── CLAUDE.md    the working agreement the AI coding agent follows
```

## Project documents

| Document | What it answers |
|---|---|
| [PRD.md](PRD.md) | What was built and why: problem, users, stories, success metrics and results, milestones, risks |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | How every number is calculated |
| [docs/EVALUATION.md](docs/EVALUATION.md) | How well the models do on live data |
| [docs/decisions/](docs/decisions/) | Why the big choices were made (React over Streamlit, ESPN over FotMob) |
| [docs/PROGRESS.md](docs/PROGRESS.md) | The build log: every task, decision and session |

## How it was built

This project is also an experiment in **product management with an AI engineer**.

1. **The product owner, Yengnong Xiong, wrote the spec**: a [PRD](PRD.md) with personas, prioritised user stories, a methodology, success metrics and milestones with acceptance criteria, plus a working agreement for an AI pair, [`CLAUDE.md`](CLAUDE.md).
2. **Claude Code built it** in time-boxed sessions, milestone by milestone (M0 to M9, then five stretch goals). It logged every task and decision in [`docs/PROGRESS.md`](docs/PROGRESS.md) and recorded larger choices as [ADRs](docs/decisions/).
3. **Guardrails kept it honest**: only passing code reaches `main`, tests are never weakened, there are no fabricated numbers, and CI acts as the contract.
4. **Then reality checked it.** Everything passed on test data, but the first run on live data exposed 20 issues. FPL had switched to full legal names, one source had vanished, and a value band was overconfident. Each was fixed test-first. The lessons are in [PRD §21](PRD.md#21-outcomes-and-lessons-learned).

## Limitations

- Player-level pressing and ball progression use **proxies** (possession-adjusted defensive actions; xGBuildup and xGChain), because pressure and progressive-pass counts need event data that isn't freely available. Proxies are badged wherever they appear.
- Without the optional self-hosted Transfermarkt API, market values come from a **June 2026 snapshot** and are labelled stale.
- The stats-implied value **learns the market's own biases**, and it is not a transfer-fee prediction.
- Candidates are **Premier League players only**. Goalkeeper ratings are limited (no free post-shot xG data) and say so.

## License, data and disclaimer

- **Code:** [MIT](LICENSE).
- **Data:** downloaded on your machine for personal, non-commercial use, never committed to this repository, and fetched politely (rate limits, caching, a descriptive User-Agent).
- This is an independent portfolio project, not affiliated with the Premier League, Fantasy Premier League, Understat, ESPN or Transfermarkt. Transfermarkt figures are **estimated market values**, not prices or fees.
