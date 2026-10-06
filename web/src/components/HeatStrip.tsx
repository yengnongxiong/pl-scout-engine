import { Link } from "react-router";

import type { Schemas } from "../api/client";
import { formatNumber } from "../lib/format";
import { positionLabel } from "../lib/labels";

type Need = Schemas["NeedOut"];

const SHADES = ["bg-white", "bg-amber-50", "bg-amber-100", "bg-amber-200", "bg-amber-300"];

/**
 * Every position group with its need severity, worst first. Shade follows severity, but the
 * number and rank are printed too, so colour is never the only signal.
 */
export function HeatStrip({ needs, linkFor }: { needs: Need[]; linkFor: (need: Need) => string }) {
  const max = Math.max(...needs.map((n) => n.severity), 0);
  return (
    <ol
      className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7"
      aria-label="Need severity by position group"
    >
      {needs.map((need) => {
        const level = max > 0 ? Math.round((need.severity / max) * (SHADES.length - 1)) : 0;
        return (
          <li key={need.need_id}>
            <Link
              to={linkFor(need)}
              className={`block rounded-md border border-slate-200 p-2 text-center hover:border-accent-600 focus:ring-2 focus:ring-accent-600 focus:outline-none ${SHADES[level] ?? "bg-white"}`}
            >
              <span className="block text-xs text-slate-600">#{need.rank}</span>
              <span className="block font-semibold text-slate-900">{need.position_group}</span>
              <span className="block text-xs text-slate-700">
                {positionLabel(need.position_group)}
              </span>
              <span className="block text-xs text-slate-800 tabular-nums">
                severity {formatNumber(need.severity)}
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
