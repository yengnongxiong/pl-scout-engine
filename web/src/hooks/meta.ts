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

/** Last season's top needs vs this season's arrivals (US-16). */
export function useBacktest() {
  return useQuery({
    queryKey: ["meta", "backtest"],
    queryFn: async () => unwrap(await api.GET("/meta/backtest")),
  });
}

/** Delta-method aging curves from past FPL seasons (US-18). */
export function useAgeCurves() {
  return useQuery({
    queryKey: ["meta", "age-curves"],
    queryFn: async () => unwrap(await api.GET("/meta/age-curves")),
    retry: false,
  });
}
