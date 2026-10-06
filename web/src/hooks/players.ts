import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "../api/client";
import type { SeasonMode } from "../lib/labels";

/** Player search by name (prefix of any word, fuzzy for typos). */
export function usePlayerSearch(q: string) {
  const query = q.trim();
  return useQuery({
    queryKey: ["players", "search", query],
    queryFn: async () =>
      unwrap(await api.GET("/players/search", { params: { query: { q: query } } })),
    enabled: query.length > 0,
    placeholderData: keepPreviousData,
  });
}

/** Player profile: header facts, percentiles with receipts, value, role, caveats. */
export function usePlayer(playerId: number | undefined, seasonMode: SeasonMode) {
  return useQuery({
    queryKey: ["player", playerId, seasonMode],
    queryFn: async () =>
      unwrap(
        await api.GET("/players/{player_id}", {
          params: { path: { player_id: playerId ?? 0 }, query: { season_mode: seasonMode } },
        }),
      ),
    enabled: playerId !== undefined,
  });
}

/** Top-k similar players (US-09). */
export function useSimilar(playerId: number | undefined, seasonMode: SeasonMode, k = 5) {
  return useQuery({
    queryKey: ["similar", playerId, seasonMode, k],
    queryFn: async () =>
      unwrap(
        await api.GET("/players/{player_id}/similar", {
          params: { path: { player_id: playerId ?? 0 }, query: { season_mode: seasonMode, k } },
        }),
      ),
    enabled: playerId !== undefined,
    retry: false,
  });
}

/** Grounded scouting report, optionally against a club's need (US-06). */
export function useReport(
  playerId: number | undefined,
  teamId: number | undefined,
  seasonMode: SeasonMode,
) {
  return useQuery({
    queryKey: ["report", playerId, teamId, seasonMode],
    queryFn: async () =>
      unwrap(
        await api.GET("/players/{player_id}/report", {
          params: {
            path: { player_id: playerId ?? 0 },
            query: { team_id: teamId, season_mode: seasonMode },
          },
        }),
      ),
    enabled: playerId !== undefined,
  });
}

/** Side-by-side KPIs of two players (US-07). */
export function useCompare(
  a: number | undefined,
  b: number | undefined,
  teamId: number | undefined,
  seasonMode: SeasonMode,
) {
  return useQuery({
    queryKey: ["compare", a, b, teamId, seasonMode],
    queryFn: async () =>
      unwrap(
        await api.GET("/compare", {
          params: { query: { a: a ?? 0, b: b ?? 0, team_id: teamId, season_mode: seasonMode } },
        }),
      ),
    enabled: a !== undefined && b !== undefined && a !== b,
  });
}

/** Next-season projection for one player from the age curves (US-18). */
export function usePlayerAgeCurve(playerId: number | undefined) {
  return useQuery({
    queryKey: ["age-curve", playerId],
    queryFn: async () =>
      unwrap(
        await api.GET("/players/{player_id}/age-curve", {
          params: { path: { player_id: playerId ?? 0 } },
        }),
      ),
    enabled: playerId !== undefined,
    retry: false,
  });
}
