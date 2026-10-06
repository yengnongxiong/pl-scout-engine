import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";

import type { Schemas } from "../api/client";
import { formatNumber } from "../lib/format";

type Curve = Schemas["AgeCurveOut"];

const STYLES = [
  { color: "#0f766e", dash: undefined },
  { color: "#b45309", dash: "6 3" },
  { color: "#4338ca", dash: "2 3" },
  { color: "#475569", dash: "10 3 2 3" },
] as const;

/**
 * Cumulative change in each per-90 rate by age, relative to the youngest age with enough
 * data. Lines differ by dash pattern as well as colour; the table beside it has the numbers.
 */
export function AgeCurveChart({ curves }: { curves: Curve[] }) {
  const ages = [...new Set(curves.flatMap((c) => c.points.map((p) => p.age)))].sort(
    (a, b) => a - b,
  );
  const data = ages.map((age) => {
    const row: Record<string, number | null> = { age };
    for (const c of curves) {
      row[c.metric] = c.points.find((p) => p.age === age)?.cumulative ?? null;
    }
    return row;
  });
  return (
    <figure>
      <LineChart
        width={560}
        height={260}
        data={data}
        margin={{ top: 10, right: 20, bottom: 20, left: 10 }}
      >
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="age" label={{ value: "Age", position: "insideBottom", offset: -10 }} />
        <YAxis tickFormatter={(v: number) => formatNumber(v, 2)} />
        <Tooltip formatter={(v) => (typeof v === "number" ? formatNumber(v, 3) : String(v))} />
        {curves.map((c, i) => {
          const style = STYLES[i % STYLES.length] ?? STYLES[0];
          return (
            <Line
              key={c.metric}
              type="monotone"
              dataKey={c.metric}
              name={c.label}
              stroke={style.color}
              strokeDasharray={style.dash}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          );
        })}
      </LineChart>
      <ul className="mt-1 flex flex-wrap gap-4 text-sm" aria-label="Legend">
        {curves.map((c, i) => {
          const style = STYLES[i % STYLES.length] ?? STYLES[0];
          return (
            <li key={c.metric} className="flex items-center gap-1.5 text-slate-800">
              <svg width="24" height="8" aria-hidden="true">
                <line
                  x1="0"
                  y1="4"
                  x2="24"
                  y2="4"
                  stroke={style.color}
                  strokeWidth="2"
                  strokeDasharray={style.dash}
                />
              </svg>
              {c.label}
            </li>
          );
        })}
      </ul>
    </figure>
  );
}
