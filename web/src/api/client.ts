/**
 * Typed HTTP client for the read-only FastAPI service.
 *
 * Types come from `schema.d.ts`, generated from `web/openapi.json` (`npm run gen:api`), so the
 * front end never duplicates API types by hand (ADR-0001).
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

/** The browser calls `/api/...`; Vite's dev/preview proxy forwards it to FastAPI. */
export const API_BASE_PATH = "/api";

function baseUrl(): string {
  return `${window.location.origin}${API_BASE_PATH}`;
}

export const api = createClient<paths>({
  baseUrl: baseUrl(),
  // Resolve fetch per call so test interceptors (MSW) and polyfills are always honoured.
  fetch: (request) => globalThis.fetch(request),
});

/** An API failure carrying the server's single error schema (PRD §12). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function isErrorResponse(value: unknown): value is Schemas["ErrorResponse"] {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const inner: unknown = value.error;
  return (
    typeof inner === "object" &&
    inner !== null &&
    "code" in inner &&
    "message" in inner &&
    typeof inner.code === "string" &&
    typeof inner.message === "string"
  );
}

/** Return the response body, or throw an {@link ApiError} for any non-2xx response. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  const { data, error, response } = result;
  if (error !== undefined || data === undefined) {
    if (isErrorResponse(error)) {
      throw new ApiError(response.status, error.error.code, error.error.message);
    }
    throw new ApiError(response.status, "http_error", `Request failed (HTTP ${response.status}).`);
  }
  return data;
}
