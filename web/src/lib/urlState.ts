import { useCallback } from "react";
import { useSearchParams } from "react-router";

import type { BenchmarkValue, SeasonMode } from "./labels";

/** Filters, season mode and benchmark live in the URL (PRD §13), so views are bookmarkable. */

export function parseIntParam(value: string | null): number | undefined {
  if (value === null || value.trim() === "") {
    return undefined;
  }
  const n = Number(value);
  return Number.isInteger(n) ? n : undefined;
}

export function parseNumberParam(value: string | null): number | undefined {
  if (value === null || value.trim() === "") {
    return undefined;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

export function parseIdList(value: string | null): number[] {
  if (!value) {
    return [];
  }
  return value
    .split(",")
    .map((part) => Number(part))
    .filter((n) => Number.isInteger(n));
}

export function parseSeasonMode(value: string | null): SeasonMode {
  return value === "current" ? "current" : "blended";
}

export function parseBenchmark(value: string | null): BenchmarkValue {
  return value === "top4" || value === "league" || value === "custom" ? value : "top6";
}

/** Read and update query params; `undefined`/empty values are removed from the URL. */
export function useQueryParams() {
  const [params, setParams] = useSearchParams();
  const update = useCallback(
    (changes: Record<string, string | number | boolean | number[] | undefined | null>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(changes)) {
            if (
              value === undefined ||
              value === null ||
              value === "" ||
              value === false ||
              (Array.isArray(value) && value.length === 0)
            ) {
              next.delete(key);
            } else if (Array.isArray(value)) {
              next.set(key, value.join(","));
            } else {
              next.set(key, value === true ? "1" : String(value));
            }
          }
          return next;
        },
        { replace: false },
      );
    },
    [setParams],
  );
  return [params, update] as const;
}

/** Season mode and benchmark shared by every page. */
export function useAnalysisParams() {
  const [params, update] = useQueryParams();
  return {
    params,
    update,
    seasonMode: parseSeasonMode(params.get("mode")),
    benchmark: parseBenchmark(params.get("benchmark")),
    custom: parseIdList(params.get("custom")),
  };
}

/** Query string carrying the shared analysis params to another page. */
export function analysisQuery(seasonMode: SeasonMode, benchmark: BenchmarkValue, custom: number[]) {
  const q = new URLSearchParams();
  if (seasonMode !== "blended") {
    q.set("mode", seasonMode);
  }
  if (benchmark !== "top6") {
    q.set("benchmark", benchmark);
  }
  if (benchmark === "custom" && custom.length > 0) {
    q.set("custom", custom.join(","));
  }
  return q;
}
