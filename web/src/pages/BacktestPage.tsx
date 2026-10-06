import { Link } from "react-router";

import type { Schemas } from "../api/client";
import { Badge } from "../components/Badges";
import { Card } from "../components/Card";
import { EmptyState, LoadingState, QueryError } from "../components/states";
import { useBacktest } from "../hooks/meta";
import { NOT_AVAILABLE, formatDate, formatInteger, formatNumber, formatShare } from "../lib/format";
import { benchmarkLabel, positionLabel } from "../lib/labels";

type Backtest = Schemas["BacktestResponse"];

export function BacktestPage() {
  const backtest = useBacktest();
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Backtest</h1>
      {backtest.isPending ? (
        <LoadingState label="Re-running last season's diagnosis…" />
      ) : backtest.isError ? (
        <QueryError
          error={backtest.error}
          onRetry={() => {
            void backtest.refetch();
          }}
        />
      ) : (
        <BacktestView data={backtest.data} />
      )}
    </div>
  );
}

function Metric({ label, value, help }: { label: string; value: string; help: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs text-slate-600">{label}</p>
      <p className="text-2xl font-semibold text-slate-900 tabular-nums">{value}</p>
      <p className="mt-1 text-xs text-slate-600">{help}</p>
    </div>
  );
}

/** The benchmark at the end of the backtest season is that season's own table. */
function benchmarkText(benchmark: string, season: string): string {
  if (benchmark === "top6" || benchmark === "top4") {
    return `the top ${benchmark.slice(3)} of the ${season} table`;
  }
  return benchmarkLabel(benchmark).toLowerCase();
}

function BacktestView({ data: d }: { data: Backtest }) {
  const n = String(d.top_n);
  const clubs = `${String(d.evaluated)} ${d.evaluated === 1 ? "club" : "clubs"}`;
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-700">
        Did the top {n} needs diagnosed at the end of <strong>{d.as_of_season}</strong> (against{" "}
        {benchmarkText(d.benchmark, d.as_of_season)}) match the position groups of the players clubs
        brought in for <strong>{d.signing_season}</strong>? An arrival is a player who has played
        for a club they had no FPL record with last season.
      </p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label={`Engine precision@${n}`}
          value={formatShare(d.precision)}
          help={`Share of each club's top ${n} needs that were signed, averaged over ${clubs}.`}
        />
        <Metric
          label={`Naive baseline precision@${n}`}
          value={formatShare(d.baseline_precision)}
          help="The most-signed groups at the other clubs, used as the same prediction."
        />
        <Metric
          label="Random expectation"
          value={formatShare(d.random_precision)}
          help="Expected precision of picking groups at random."
        />
        <Metric
          label="Clubs with at least one hit"
          value={formatShare(d.hit_rate)}
          help="Share of evaluated clubs where a top need was signed."
        />
      </div>
      <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
        {d.caveat}
      </p>
      {d.evaluated === 0 ? (
        <EmptyState title="Nothing to evaluate yet">
          No club has both a shortfall at the end of {d.as_of_season} and an arrival this season.
          The backtest fills in as the transfer window&apos;s signings play.
        </EmptyState>
      ) : null}
      <Card
        title="By club"
        footer={
          <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-600">
            FPL history ({d.as_of_season}) · as of {formatDate(d.history_as_of)} | FPL (
            {d.signing_season}) · as of {formatDate(d.arrivals_as_of)}
          </p>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Predicted needs and actual arrivals per club</caption>
            <thead className="text-xs text-slate-600">
              <tr>
                <th scope="col" className="py-1">
                  Club
                </th>
                <th scope="col">Top needs (severity)</th>
                <th scope="col">Arrivals</th>
                <th scope="col">Precision</th>
                <th scope="col">Baseline</th>
              </tr>
            </thead>
            <tbody>
              {d.clubs.map((c) => (
                <tr key={c.team_id} className="border-t border-slate-100 align-top">
                  <td className="py-2 pr-2 font-medium">{c.team_name}</td>
                  <td className="pr-2">
                    {c.predicted.length === 0 ? (
                      <span className="text-slate-600">no shortfall</span>
                    ) : (
                      <ul>
                        {c.predicted.map((p) => (
                          <li key={p.position_group}>
                            <span title={positionLabel(p.position_group)}>{p.position_group}</span>{" "}
                            ({formatNumber(p.severity)}){" "}
                            {c.hits.includes(p.position_group) ? (
                              <Badge tone="good">signed</Badge>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td className="pr-2">
                    {c.arrivals.length === 0 ? (
                      <span className="text-slate-600">none yet</span>
                    ) : (
                      <ul>
                        {c.arrivals.map((a) => (
                          <li key={a.player_id}>
                            <Link
                              to={`/players/${a.player_id}`}
                              className="text-accent-800 underline"
                            >
                              {a.player_name}
                            </Link>{" "}
                            ({a.position_group ?? NOT_AVAILABLE}, {formatInteger(a.minutes)} min)
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td className="tabular-nums">{formatShare(c.precision)}</td>
                  <td className="tabular-nums">
                    {formatShare(c.baseline_precision)}
                    {c.baseline_groups.length > 0 ? (
                      <span className="block text-xs text-slate-600">
                        {c.baseline_groups.join(", ")}
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {Object.keys(d.skipped).length > 0 ? (
          <p className="mt-2 text-xs text-slate-600">
            Not evaluated:{" "}
            {Object.entries(d.skipped)
              .map(([reason, count]) => `${reason} ${String(count)}`)
              .join(", ")}
            .
          </p>
        ) : null}
      </Card>
    </div>
  );
}
