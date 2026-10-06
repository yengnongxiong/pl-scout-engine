import {
  CartesianGrid,
  ReferenceLine,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Schemas } from "../api/client";
import { formatEurMillions } from "../lib/format";

type Candidate = Schemas["CandidateOut"];

const EUR_PER_MILLION = 1_000_000;
const SERIES = [
  { label: "Undervalued", color: "#047857", shape: "triangle", glyph: "▲" },
  { label: "Fair", color: "#475569", shape: "circle", glyph: "●" },
  { label: "Premium", color: "#b45309", shape: "square", glyph: "■" },
] as const;

interface Point {
  name: string;
  tm: number;
  implied: number;
}

/**
 * Transfermarkt estimated market value vs stats-implied value (US-11). Labels use both
 * colour and marker shape; the table next to it carries the same numbers as text.
 */
export function MoneyballChart({ candidates }: { candidates: Candidate[] }) {
  const scored = candidates.filter((c) => c.market_value && c.implied_value);
  if (scored.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        Not available: no candidate has both a Transfermarkt estimated market value and a
        stats-implied value (run <code>scout train</code>).
      </p>
    );
  }
  const points = (label: string): Point[] =>
    scored
      .filter((c) => c.implied_value?.label === label)
      .map((c) => ({
        name: c.player_name,
        tm: (c.market_value?.value_eur ?? 0) / EUR_PER_MILLION,
        implied: (c.implied_value?.implied_value_eur ?? 0) / EUR_PER_MILLION,
      }));
  const max = Math.max(
    ...scored.map((c) =>
      Math.max(c.market_value?.value_eur ?? 0, c.implied_value?.implied_value_eur ?? 0),
    ),
  );
  const top = Math.ceil((max / EUR_PER_MILLION) * 1.1);
  return (
    <figure>
      <ScatterChart width={560} height={320} margin={{ top: 10, right: 20, bottom: 40, left: 30 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis
          type="number"
          dataKey="tm"
          name="Transfermarkt estimated market value"
          unit="m"
          domain={[0, top]}
          label={{
            value: "Transfermarkt estimated market value (€m)",
            position: "insideBottom",
            offset: -25,
          }}
        />
        <YAxis
          type="number"
          dataKey="implied"
          name="Stats-implied value"
          unit="m"
          domain={[0, top]}
          label={{
            value: "Stats-implied value (€m)",
            angle: -90,
            position: "insideLeft",
            offset: -15,
            style: { textAnchor: "middle" },
          }}
        />
        <ReferenceLine
          segment={[
            { x: 0, y: 0 },
            { x: top, y: top },
          ]}
          stroke="#94a3b8"
        />
        <Tooltip
          formatter={(value) =>
            typeof value === "number" ? formatEurMillions(value * EUR_PER_MILLION) : String(value)
          }
        />
        {SERIES.map((s) => (
          <Scatter
            key={s.label}
            name={s.label}
            data={points(s.label)}
            fill={s.color}
            shape={s.shape}
          />
        ))}
      </ScatterChart>
      <ul className="mt-1 flex gap-4 text-sm" aria-label="Legend">
        {SERIES.map((s) => (
          <li key={s.label} className="flex items-center gap-1.5 text-slate-800">
            <span aria-hidden="true" style={{ color: s.color }}>
              {s.glyph}
            </span>
            {s.label} ({points(s.label).length})
          </li>
        ))}
      </ul>
      <figcaption className="mt-1 text-xs text-slate-600">
        Above the diagonal: the stats imply more than the market estimate. Stats-implied value is
        not a fee prediction; the model learns the market&apos;s own biases.
      </figcaption>
    </figure>
  );
}
