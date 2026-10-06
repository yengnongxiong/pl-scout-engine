/**
 * Synthetic MSW handlers for front-end tests. Every value here is made up for testing and never
 * reaches the real app (CLAUDE.md data integrity rule 1).
 */
import { http, HttpResponse } from "msw";

import type { Schemas } from "../api/client";
import * as data from "./data.synthetic";

/** Match `/api/<path>` on any origin. */
export function apiPath(path: string): string {
  return `*/api${path}`;
}

export const syntheticHealth: Schemas["HealthResponse"] = {
  status: "ok",
  version: "0.0.0-test",
  warehouse_version: "synthetic-build",
};

export function errorBody(code: string, message: string): Schemas["ErrorResponse"] {
  return { error: { code, message, details: {} } };
}

export const handlers = [
  http.get(apiPath("/health"), () => HttpResponse.json(syntheticHealth)),
  http.get(apiPath("/teams"), () => HttpResponse.json(data.teams)),
  http.get(apiPath("/teams/search"), ({ request }) =>
    HttpResponse.json(data.teamSearch(new URL(request.url).searchParams.get("q") ?? "")),
  ),
  http.get(apiPath("/teams/:teamId/diagnosis"), () => HttpResponse.json(data.diagnosis)),
  http.get(apiPath("/teams/:teamId/recommendations"), () => HttpResponse.json(data.shortlist)),
  http.get(apiPath("/players/search"), () => HttpResponse.json(data.playerSearch)),
  http.get(apiPath("/players/:playerId/similar"), () => HttpResponse.json(data.similar)),
  http.get(apiPath("/players/:playerId/report"), () => HttpResponse.json(data.report)),
  http.get(apiPath("/players/:playerId"), ({ params }) =>
    HttpResponse.json(params.playerId === "7" ? data.incumbentSheet : data.factSheet),
  ),
  http.get(apiPath("/compare"), () => HttpResponse.json(data.compare)),
  http.get(apiPath("/meta/freshness"), () => HttpResponse.json(data.freshness)),
  http.get(apiPath("/meta/methodology"), () => HttpResponse.json(data.methodology)),
  http.get(apiPath("/meta/backtest"), () => HttpResponse.json(data.backtest)),
];
