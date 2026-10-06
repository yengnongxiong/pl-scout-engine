import { NOT_AVAILABLE, formatOrdinal } from "../lib/format";
import { ProxyBadge } from "./Badges";

/**
 * Horizontal percentile bar (PRD §13: bars, not radars). The number is always printed next
 * to the bar, so colour and length are never the only signal; a missing percentile shows
 * "Not available", never an empty-looking zero.
 */
export function PercentileBar({
  label,
  percentile,
  detail,
  isProxy = false,
  proxyFor,
  highlight = false,
  tone = "accent",
  showLabel = true,
}: {
  label: string;
  percentile: number | null | undefined;
  detail?: string;
  isProxy?: boolean;
  proxyFor?: string | null;
  highlight?: boolean;
  tone?: "accent" | "slate";
  /** Hide the label visually (e.g. in a table row that already names the KPI). */
  showLabel?: boolean;
}) {
  const known = percentile !== null && percentile !== undefined && !Number.isNaN(percentile);
  const value = known ? Math.max(0, Math.min(100, percentile)) : 0;
  const text = known ? `${formatOrdinal(percentile)} percentile` : NOT_AVAILABLE;
  const fill = tone === "accent" ? "bg-accent-600" : "bg-slate-500";
  return (
    <div className={highlight ? "rounded bg-amber-50 p-1" : "p-1"}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 text-sm">
        <span className={showLabel ? "flex items-center gap-1.5 text-slate-800" : "sr-only"}>
          {label}
          {isProxy ? <ProxyBadge proxyFor={proxyFor} /> : null}
          {highlight ? (
            <span className="text-xs font-medium text-amber-900">(club need)</span>
          ) : null}
        </span>
        <span className="text-slate-700 tabular-nums">
          {text}
          {detail ? <span className="text-slate-600"> · {detail}</span> : null}
        </span>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={known ? Math.round(value) : undefined}
        aria-valuetext={text}
        className={`relative mt-1 h-2.5 rounded ${known ? "bg-slate-200" : "border border-dashed border-slate-300"}`}
      >
        {known ? <div className={`h-full rounded ${fill}`} style={{ width: `${value}%` }} /> : null}
        <div className="absolute inset-y-0 left-1/2 w-px bg-slate-400" aria-hidden="true" />
      </div>
    </div>
  );
}
