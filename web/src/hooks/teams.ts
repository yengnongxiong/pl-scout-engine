import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "../api/client";
import type { BenchmarkValue, SeasonMode } from "../lib/labels";

/** Clubs in the current season. */
export function useTeams() {
  return useQuery({
    queryKey: ["teams"],
    queryFn: async () => unwrap(await api.GET("/teams")),
  });
}

/** Club search by name or alias (US-01); disabled for an empty query. */
export function useTeamSearch(q: string) {
  const query = q.trim();
  return useQuery({
    queryKey: ["teams", "search", query],
    queryFn: async () =>
      unwrap(await api.GET("/teams/search", { params: { query: { q: query } } })),
    enabled: query.length > 0,
    placeholderData: keepPreviousData,
  });
}

export interface AnalysisOptions {
  seasonMode: SeasonMode;
  benchmark: BenchmarkValue;
  custom: number[];
}

function benchmarkQuery({ seasonMode, benchmark, custom }: AnalysisOptions) {
  return {
    season_mode: seasonMode,
    benchmark,
    custom: benchmark === "custom" ? custom : undefined,
  };
}

/** A club's ranked needs with evidence (US-02/03). */
export function useDiagnosis(teamId: number | undefined, options: AnalysisOptions) {
  const ready =
    teamId !== undefined && (options.benchmark !== "custom" || options.custom.length > 0);
  return useQuery({
    queryKey: ["diagnosis", teamId, options],
    queryFn: async () =>
      unwrap(
        await api.GET("/teams/{team_id}/diagnosis", {
          params: { path: { team_id: teamId ?? 0 }, query: benchmarkQuery(options) },
        }),
      ),
    enabled: ready,
  });
}

export interface ShortlistFilters {
  maxValueEur?: number | undefined;
  minAge?: number | undefined;
  maxAge?: number | undefined;
  minMinutes?: number | undefined;
  excludeTeamIds: number[];
  includeSideways: boolean;
}

/** Ranked candidates for one need (US-04/05). */
export function useShortlist(
  teamId: number | undefined,
  needId: string | undefined,
  options: AnalysisOptions,
  filters: ShortlistFilters,
) {
  return useQuery({
    queryKey: ["shortlist", teamId, needId, options, filters],
    queryFn: async () =>
      unwrap(
        await api.GET("/teams/{team_id}/recommendations", {
          params: {
            path: { team_id: teamId ?? 0 },
            query: {
              ...benchmarkQuery(options),
              need_id: needId,
              max_value_eur: filters.maxValueEur,
              min_age: filters.minAge,
              max_age: filters.maxAge,
              min_minutes: filters.minMinutes,
              exclude_team_ids: filters.excludeTeamIds.length ? filters.excludeTeamIds : undefined,
              include_sideways: filters.includeSideways,
            },
          },
        }),
      ),
    enabled: teamId !== undefined && needId !== undefined,
    placeholderData: keepPreviousData,
  });
}
