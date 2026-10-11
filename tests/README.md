# Tests

How the engine is checked. Every test runs offline on small, made-up ("synthetic") data,
and a guard blocks network access, so results never depend on a live website.

| Folder | What it covers |
|---|---|
| [`unit/`](unit/) | One piece at a time: every formula checked against a hand calculation, each data structure against a reference implementation, each data-source adapter against its expected format (including a "the source changed its format" failure), the models, the report writer and its fact checker. |
| [`integration/`](integration/) | The pieces together: a full build from raw files to the database, every SQL query against a pandas equivalent, every API endpoint, database migrations, and the same build on SQLite and Postgres giving identical answers. |
| [`fixtures/`](fixtures/) | The small synthetic inputs the tests use (file names contain `synthetic`). No real scraped data is ever committed. |

```bash
uv run pytest            # about 460 tests
uv run ruff check . && uv run mypy src
```

The dashboard has its own tests in [`../web/`](../web/README.md). GitHub Actions runs everything
on every push: Python, Postgres parity, web, and an API-contract check.
