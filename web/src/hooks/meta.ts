import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "../api/client";

/** Per-source freshness, coverage and validation status (US-08). */
export function useFreshness() {
  return useQuery({
    queryKey: ["meta", "freshness"],
    queryFn: async () => unwrap(await api.GET("/meta/freshness")),
  });
}

/** KPI definitions, weights, thresholds, model runs and limitations (US-08). */
export function useMethodology() {
  return useQuery({
    queryKey: ["meta", "methodology"],
    queryFn: async () => unwrap(await api.GET("/meta/methodology")),
  });
}
