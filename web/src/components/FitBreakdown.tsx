import { NOT_AVAILABLE, formatScore, formatShare } from "../lib/format";
import { FIT_COMPONENTS, FIT_ORDER } from "../lib/labels";

/** FitScore components with the (renormalised) weights actually used (PRD §8.9). */
export function FitBreakdown({
  components,
  weightsUsed,
  compact = false,
}: {
  components: Record<string, number | null>;
  weightsUsed: Record<string, number>;
  compact?: boolean;
}) {
  return (
    <dl className={compact ? "space-y-1" : "space-y-2"}>
      {FIT_ORDER.map((name) => {
        const value = components[name];
        const weight = weightsUsed[name];
        const meta = FIT_COMPONENTS[name] ?? { label: name, help: "" };
        const known = value !== null && value !== undefined;
        return (
          <div key={name} className="grid grid-cols-[7.5rem_1fr_6rem] items-center gap-2 text-xs">
            <dt className="text-slate-700" title={meta.help}>
              {meta.label}
            </dt>
            <dd className="h-2 rounded bg-slate-200" aria-hidden="true">
              {known ? (
                <div
                  className="h-full rounded bg-accent-600"
                  style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
                />
              ) : null}
            </dd>
            <dd className="text-right text-slate-700 tabular-nums">
              {known ? formatScore(value) : NOT_AVAILABLE}
              {known && weight !== undefined ? (
                <span className="text-slate-600"> ×{formatShare(weight)}</span>
              ) : null}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
