# The engine (`src/scout/`)

The Python back end is a pipeline. Data flows left to right, and each layer only uses the
layers to its left, so every piece can be understood and tested on its own:

```text
ingest  →  transform  →  db  →  features  →  engines / ml  →  reports  →  api
```

| Folder | In plain English | Technical detail |
|---|---|---|
| [`ingest/`](ingest/) | **Collects data** from free sources (Fantasy Premier League, Understat, ESPN, Transfermarkt, history archives) politely and saves an untouched copy. | One adapter per source behind a common `SourceAdapter` interface; rate limiting, caching, retries and schema checks that fail loudly when a source changes. |
| [`transform/`](transform/) | **Cleans and connects** the data: checks it, and works out that "Bruno Fernandes" in one source is "Bruno Borges Fernandes" in another. | pandera validation; entity resolution with club blocking, name scoring, date-of-birth checks and union-find. |
| [`db/`](db/) | **Stores** everything in a database, where each number keeps its source and timestamp. | SQLAlchemy star schema, Alembic migrations, analytical SQL (CTEs, window functions) in [`db/sql/`](db/sql/), SQLite by default, Postgres optional. |
| [`features/`](features/) | **Turns raw stats into fair comparisons**: per-90 rates, blending this season with last while samples are small, adjusting defensive stats for possession, percentiles among position peers. | Pure, hand-tested functions; results materialised into `player_season_features`. |
| [`engines/`](engines/) | **Makes the decisions**: finds a club's weakest areas, scores candidates (FitScore), compares them with the current starter, searches names, backtests the diagnosis. | `diagnosis.py`, `recommend.py`, `fit.py`, `style.py`, `backtest.py`, `search.py`. |
| [`ml/`](ml/) | **Machine learning**: groups players into playing styles, finds similar players, estimates a stats-implied market value, and projects how output changes with age. | Gaussian mixture models, cosine similarity, gradient-boosted trees with conformal bands, delta-method age curves; all seeded and evaluated. |
| [`reports/`](reports/) | **Writes the scouting report** in plain English, then checks that every number in it really exists in the data. | Fact sheet, Jinja2 templates, optional local LLM (Ollama), grounding validator, PDF/Markdown export. |
| [`api/`](api/) | **Serves the dashboard** over HTTP. | FastAPI, typed schemas exported to OpenAPI, LRU-cached hot endpoints, one error format. |
| [`dsa/`](dsa/) | **Hand-written data structures** used throughout. | Heap top-k, k-d tree, LRU cache, token bucket, union-find, trie, Levenshtein distance; each with complexity notes and tests. |

Entry points: [`cli.py`](cli.py) (the `scout` command), [`demo.py`](demo.py) (`scout demo`, one
command from nothing to a running dashboard) and [`pipeline.py`](pipeline.py) (build and
train). Settings come from [`config.py`](config.py), which loads and validates
[`../../config/`](../../config/README.md).
