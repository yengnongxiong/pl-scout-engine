# ADR-0001: React + TypeScript front end instead of Streamlit

- Status: Accepted
- Date: 2026-10-03
- Decider: Yengnong Xiong (owner)

## Context
PRD v1.0 chose Streamlit for the dashboard because it is quick to build and keeps the stack all-Python. The project also has to demonstrate software-engineering depth for SWE internship applications, and the architecture is already API-first (PRD §10), so the UI can be replaced without touching the engine.

## Decision
Build the dashboard as a React + TypeScript single-page app in `web/`, consuming the existing FastAPI service. Remove Streamlit from the stack.

## Consequences
- Stronger SWE signal: component architecture, typed API client, front-end testing. Roughly double the UI effort in M8.
- End-to-end type safety: FastAPI's OpenAPI schema is exported to `web/openapi.json` and TypeScript types are generated from it; CI fails on drift.
- Two toolchains (Python + Node) in CI.

## PRD changes (apply in M0, bump PRD to v1.1, add a changelog line at the top)
1. §10 diagram: replace `API --> UI[Streamlit dashboard]` with `API --> UI["React + TypeScript SPA<br/>(Vite)"]`.
2. §10 "API-first" bullet → "**API-first:** the React app talks to the API over HTTP through a client generated from the API's OpenAPI schema, so front end and back end evolve independently and stay type-safe end to end."
3. §10.1 tech stack: replace the `UI` row with these rows:
   - `| Front end | React + TypeScript (strict), Vite, React Router, TanStack Query, TanStack Table, Recharts, Tailwind CSS |`
   - `| API types | openapi-typescript + openapi-fetch, generated from FastAPI's OpenAPI schema |`
   - `| Front-end quality | Vitest, React Testing Library, MSW, ESLint, Prettier; Playwright smoke test (stretch) |`
4. §12: add after the table: "The OpenAPI schema is exported with `scout export-openapi` to `web/openapi.json`. In development the Vite dev server proxies `/api` to FastAPI; CORS allows only `http://localhost:5173`."
5. §13: replace the whole section with "New §13" below.
6. §14: add "Front end: production build loads in < 2 s locally; route changes with cached data < 300 ms."
7. §16:
   - M0: append "plus a `web/` scaffold (Vite + React + TypeScript, ESLint, Prettier, Vitest) so CI covers both stacks from day one."
   - Replace the M8 row with: "Dashboard (React + TypeScript) | All P0 stories demoable on real local data; client generated from OpenAPI; page tests in loading/empty/error/success states; `npm run lint`, `typecheck`, `test` and `build` pass in CI."
8. §18: add row "Front end | React + TypeScript SPA, typed client generated from OpenAPI, TanStack Query caching, component tests."
9. §19: mark Q1 resolved by this ADR, and Q2–Q3 resolved by the defaults in CLAUDE.md "Locked decisions". Q4 stays open for the owner.

## New §13

### 13. Dashboard (React + TypeScript SPA)

| Route | Page | Contents |
|---|---|---|
| `/` | Club Diagnosis | Club search (aliases), season mode, benchmark; top needs; position-group heat strip; weak links; depth/age/contract risks |
| `/clubs/:teamId/needs/:needId` | Shortlist | Ranked candidates, filters (max value, age, minutes, exclude clubs), fit-component bars, Moneyball view toggle |
| `/players/:playerId` | Player | Header facts, percentile bars vs position peers, availability, similar players, role archetype, scouting report with copy button |
| `/compare?a=&b=` | Compare | Candidate vs incumbent, side-by-side bars with deltas |
| `/methodology` | Methodology & Data | Sources, freshness, KPI definitions, weights, proxies, limitations |

Behaviour:
- Filters, season mode and benchmark live in the URL, so every view is bookmarkable and the back button works.
- Server state is handled by TanStack Query (caching, retries). No global state library unless clearly needed.
- Every view has loading, empty ("Not available" / "Run `scout ingest`") and error states.

Design principles:
- Minimal and calm: light theme, one accent colour, at most ~3 charts per view.
- Horizontal percentile bars instead of radars.
- Consistent rounding: 1 decimal for per-90, € m for values.
- Every chart footer shows "Source · as of"; proxy badges where relevant.
- Keyboard accessible, AA contrast, colour never the only signal.
- Designed for laptop screens; mobile is not a target.