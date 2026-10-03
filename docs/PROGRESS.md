# Progress
Status: IN_PROGRESS            <!-- IN_PROGRESS or COMPLETE -->
Active session: 20261003T1917Z-2292 started 2026-10-03T19:17:02Z
Current milestone: M0

## Plan for this session
- M0-01 Apply ADR-0001 to PRD (v1.1)
- M0-02 Python package skeleton (pyproject, uv, ruff/mypy/pytest, config, Typer CLI)
- M0-03 web/ scaffold (Vite + React + TS, ESLint, Prettier, Vitest)

## Task queue (current milestone)
- [x] M0-01 Apply ADR-0001 edits to PRD, bump to v1.1 + changelog — PRD diff matches ADR list
- [x] M0-02 Python skeleton: pyproject (uv), src/scout package, errors.py, config.py (pydantic-settings + YAML), Typer CLI with `--help`, conftest network guard — `uv run scout --help`, pytest, ruff, mypy pass
- [x] M0-03 config/*.yaml stubs (settings, kpis, fit_weights, positions, team_aliases) loaded + validated by config.py — unit tests pass
- [ ] M0-04 web/ scaffold: Vite + React + TS strict, ESLint, Prettier, Vitest + RTL, Tailwind — lint/typecheck/test/build pass
- [ ] M0-05 FastAPI stub (`/health`) + `scout export-openapi` + `npm run gen:api` (openapi-typescript) — generated files committed, no drift
- [ ] M0-06 CI workflow (python, web, contract jobs) + ADR template + README stub + Makefile + .env.example + .gitignore — workflow file valid; local equivalents pass

## Done

## Blocked
- **Package registries blocked in the cloud sandbox** (2026-10-03): pypi.org and registry.npmjs.org return `403 host_not_allowed` from the egress proxy, so `uv sync` / `npm ci` can't run. Python checks ran locally against preinstalled packages (ruff, pytest and mypy all pass apart from the missing typer/types-PyYAML imports). GitHub Actions CI is the authoritative check. M0-04/M0-05 (web scaffold, `package-lock.json`, FastAPI + OpenAPI) need npm/PyPI and wait until the owner allows those hosts. `uv.lock` isn't committed yet for the same reason; generate it once PyPI is reachable.

## Questions for Yengnong (non-blocking; default chosen)
- Please allow `pypi.org`, `files.pythonhosted.org` and `registry.npmjs.org` (or the Trusted network level) in the routine's environment. Default until then: Python work verified via CI, web work paused.

## Decisions log (minor)
- 2026-10-03: `config/kpis.yaml` defines each KPI once under `kpis:` and position groups reference KPI ids with weights (PRD §8.7 shape, deduplicated). Validated: weights sum to 1, proxies need `proxy_for`.
- 2026-10-03: Dependencies added: typer (CLI), pydantic + pydantic-settings (config/API models), PyYAML (config), fastapi + uvicorn (API, M7), pytest/pytest-cov/ruff/mypy/types-PyYAML/httpx (dev quality and TestClient). All MIT/BSD/Apache.
- 2026-10-03: Commits are authored as Yengnong Xiong (GitHub noreply email) per owner request; Claude stays as Co-Authored-By. Set in CLAUDE.md session protocol step 4.

## Session log (keep the last 15 entries; summarize older ones in one line)
