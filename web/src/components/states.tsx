import type { ReactNode } from "react";

import { ApiError } from "../api/client";

/** Loading placeholder announced to screen readers. */
export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="py-8 text-sm text-slate-600">
      <span className="mr-2 inline-block h-3 w-3 animate-pulse rounded-full bg-accent-600" />
      {label}
    </div>
  );
}

/** Error panel with the server's message and an optional retry. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError
      ? error.message
      : "The API could not be reached. Is `uv run scout api` running?";
  return (
    <div role="alert" className="my-4 rounded-md border border-red-300 bg-red-50 p-4 text-sm">
      <p className="font-semibold text-red-800">Something went wrong</p>
      <p className="mt-1 text-red-800">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded border border-red-400 bg-white px-3 py-1 text-red-800 hover:bg-red-100 focus:ring-2 focus:ring-red-500 focus:outline-none"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}

/** Empty state: nothing to show, plus what to do about it. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="my-4 rounded-md border border-dashed border-slate-300 bg-white p-6 text-sm">
      <p className="font-semibold text-slate-800">{title}</p>
      {children ? <div className="mt-1 text-slate-600">{children}</div> : null}
    </div>
  );
}

/** Error panel, or the "no data yet" empty state when the warehouse has not been built. */
export function QueryError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (error instanceof ApiError && error.code === "warehouse_not_ready") {
    return (
      <EmptyState title="No data yet">
        <p>
          The warehouse has not been built. Run <code>uv run scout demo</code> (or{" "}
          <code>scout ingest</code>, <code>scout build</code> and <code>scout train</code>) and
          reload.
        </p>
      </EmptyState>
    );
  }
  if (error instanceof ApiError && error.status === 404) {
    return <EmptyState title="Not available">{error.message}</EmptyState>;
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}
