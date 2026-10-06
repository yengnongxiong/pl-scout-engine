/**
 * Synthetic MSW handlers for front-end tests. Every value here is made up for testing and never
 * reaches the real app (CLAUDE.md data integrity rule 1).
 */
import { http, HttpResponse } from "msw";

import type { Schemas } from "../api/client";

/** Match `/api/<path>` on any origin. */
export function apiPath(path: string): string {
  return `*/api${path}`;
}

export const syntheticHealth: Schemas["HealthResponse"] = {
  status: "ok",
  version: "0.0.0-test",
  warehouse_version: "synthetic-build",
};

export const handlers = [http.get(apiPath("/health"), () => HttpResponse.json(syntheticHealth))];
