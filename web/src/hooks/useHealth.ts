import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "../api/client";

/** Liveness and warehouse version of the API (`GET /health`). */
export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async () => unwrap(await api.GET("/health")),
  });
}
