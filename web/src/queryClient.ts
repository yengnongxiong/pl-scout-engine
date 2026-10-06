import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./api/client";

const STALE_MS = 5 * 60 * 1000;
const MAX_RETRIES = 2;

/** Server state cache. The warehouse only changes on `scout build`, so data stays fresh long. */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: STALE_MS,
        refetchOnWindowFocus: false,
        // A 4xx (unknown team, bad filter) will not fix itself; only retry server/network errors.
        retry: (failureCount, error) =>
          !(error instanceof ApiError && error.status < 500) && failureCount < MAX_RETRIES,
      },
    },
  });
}
