# The dashboard (`web/`)

A React + TypeScript single-page app. It only talks to the engine's API, and it never
calculates a number itself: everything on screen comes from the API with its source and date.

## Pages

| Page               | URL                      | What you can do                                                                                                                     |
| ------------------ | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Club diagnosis     | `/`                      | Pick a club and see its needs by position, the stats behind each one, weak links and squad risks.                                   |
| Shortlist          | `/clubs/:id/needs/:need` | See ranked candidates for a need, open the FitScore breakdown, filter by value, age and minutes, and switch on the Moneyball view.  |
| Player             | `/players/:id`           | Percentiles against position peers, value, age curve, similar players, and a scouting report to copy or download (PDF or Markdown). |
| Compare            | `/compare`               | Two players side by side, with the club's need KPIs highlighted.                                                                    |
| Backtest           | `/backtest`              | Did last season's diagnosed needs match the positions clubs then signed?                                                            |
| Methodology & data | `/methodology`           | Data freshness, KPI definitions and weights, thresholds, model runs, limitations.                                                   |

## How it is built

- **Typed end to end:** `openapi.json` is exported from the API (`uv run scout export-openapi`)
  and `src/api/schema.d.ts` is generated from it (`npm run gen:api`). CI fails if they drift.
- **Data fetching:** TanStack Query hooks in [`src/hooks/`](src/hooks/); filters, season mode and
  benchmark live in the URL, so every view is shareable.
- **Structure:** [`src/pages/`](src/pages/) (one file per page, each with tests),
  [`src/components/`](src/components/) (reusable pieces such as the club picker, percentile bars
  and charts), [`src/lib/`](src/lib/) (all number, money and date formatting in one place).
- **Accessible:** keyboard navigation, labels, AA contrast, and colour is never the only signal
  (numbers and shapes are always shown too).
- **Tested:** Vitest + Testing Library + MSW; every page is tested in its loading, empty, error
  and success states, with synthetic data only.

## Commands

```bash
npm ci              # install
npm run dev         # http://localhost:5173 (proxies /api to the engine on :8000)
npm run lint && npm run typecheck && npm run test && npm run build
SCOUT_SCREENSHOT_TEAM="Man Utd" npm run screenshots -- --live   # README screenshots
```

Usually you don't run these by hand: `uv run scout demo` from the repository root starts
both the API and this app.
