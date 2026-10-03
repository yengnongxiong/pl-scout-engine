# PL Scout Engine

A local, explainable recruitment dashboard for the Premier League. Pick a club, see where the
squad is weakest against a benchmark, and get Premier League players who fix it, each with a
transparent fit score, a Transfermarkt estimated market value (with its as-of date) and a
scouting report. **No number without a receipt.**

> Status: early development (milestone M0). See [`PRD.md`](PRD.md) for scope and
> [`docs/PROGRESS.md`](docs/PROGRESS.md) for the build log.

## Quick start (development)

```bash
uv sync --all-extras
uv run scout --help
uv run scout config-check
make check            # ruff, mypy, pytest
```

`uv run scout demo` (ingest → build → train → API + web app in one command) arrives in a later
milestone and will be documented here.

## Stack
Python 3.12 (uv, Typer, pydantic, FastAPI) back end; React + TypeScript (Vite) front end
(ADR-0001). Free data sources only; personal, non-commercial use; not publicly deployed.
