import { Link } from "react-router";

import type { Schemas } from "../api/client";
import { AnalysisControls } from "../components/AnalysisControls";
import { ProxyBadge, StaleBadge } from "../components/Badges";
import { Card } from "../components/Card";
import { PercentileBar } from "../components/PercentileBar";
import { PlayerPicker } from "../components/PlayerPicker";
import { Receipt } from "../components/Receipt";
import { EmptyState, LoadingState, QueryError } from "../components/states";
import { useCompare } from "../hooks/players";
import {
  NOT_AVAILABLE,
  formatAge,
  formatDate,
  formatEurMillions,
  formatGap,
  formatInteger,
  formatPer90,
} from "../lib/format";
import { positionLabel } from "../lib/labels";
import { parseIntParam, useAnalysisParams } from "../lib/urlState";

type Compare = Schemas["CompareResponse"];
type Player = Schemas["ComparePlayer"];

export function ComparePage() {
  const { params, update, seasonMode, benchmark, custom } = useAnalysisParams();
  const a = parseIntParam(params.get("a"));
  const b = parseIntParam(params.get("b"));
  const teamId = parseIntParam(params.get("team"));
  const compare = useCompare(a, b, teamId, seasonMode);
  return (
    <div className="space-y-6">
      <header className="space-y-4">
        <h1 className="text-2xl font-semibold text-slate-900">Compare players</h1>
        <div className="grid gap-4 md:grid-cols-2">
          <PlayerPicker
            label={a === undefined ? "Player A (candidate)" : "Change player A"}
            onSelect={(hit) => {
              update({ a: hit.player_id });
            }}
          />
          <PlayerPicker
            label={b === undefined ? "Player B (incumbent)" : "Change player B"}
            onSelect={(hit) => {
              update({ b: hit.player_id });
            }}
          />
        </div>
        <AnalysisControls
          seasonMode={seasonMode}
          benchmark={benchmark}
          custom={custom}
          showBenchmark={false}
          onChange={(c) => {
            update({ mode: c.mode });
          }}
        />
      </header>
      {a === undefined || b === undefined ? (
        <EmptyState title="Pick two players">
          Choose a candidate and the player to compare against (usually the club&apos;s incumbent).
        </EmptyState>
      ) : a === b ? (
        <EmptyState title="Pick two different players" />
      ) : compare.isPending ? (
        <LoadingState label="Lining up the numbers…" />
      ) : compare.isError ? (
        <QueryError
          error={compare.error}
          onRetry={() => {
            void compare.refetch();
          }}
        />
      ) : (
        <CompareView data={compare.data} />
      )}
    </div>
  );
}

function PlayerSummary({ player: p, tag }: { player: Player; tag: string }) {
  const mv = p.market_value;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs font-semibold text-slate-600">{tag}</p>
      <h2 className="text-lg font-semibold">
        <Link to={`/players/${p.player_id}`} className="text-accent-800 underline">
          {p.player_name}
        </Link>
      </h2>
      <p className="text-sm text-slate-700">
        {p.team_name} · {positionLabel(p.position_group)} · age {formatAge(p.age)} ·{" "}
        {formatInteger(p.minutes)} min ({formatInteger(p.effective_minutes)} effective)
      </p>
      <p className="text-sm text-slate-700">
        Transfermarkt estimated market value:{" "}
        {mv ? (
          <>
            {formatEurMillions(mv.value_eur)} (TM as of {formatDate(mv.tm_last_updated)}){" "}
            {mv.is_stale ? <StaleBadge /> : null}
          </>
        ) : (
          NOT_AVAILABLE
        )}
      </p>
    </div>
  );
}

function CompareView({ data: d }: { data: Compare }) {
  const receipts = d.rows.flatMap((r) =>
    [r.a, r.b].filter((k) => k !== null).map((k) => ({ source: k.source, asOf: k.as_of })),
  );
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <PlayerSummary player={d.a} tag="A" />
        <PlayerSummary player={d.b} tag="B" />
      </div>
      <Card
        title={`Percentiles side by side${d.team ? ` · ${d.team.name} need KPIs highlighted` : ""}`}
        footer={<Receipt items={receipts} />}
      >
        <table className="w-full text-left text-sm">
          <caption className="sr-only">
            Percentile of each player per KPI and the difference (A minus B)
          </caption>
          <thead className="text-xs text-slate-600">
            <tr>
              <th scope="col" className="w-1/3 py-1">
                KPI
              </th>
              <th scope="col">{d.a.player_name}</th>
              <th scope="col">{d.b.player_name}</th>
              <th scope="col" className="text-right">
                A − B
              </th>
            </tr>
          </thead>
          <tbody>
            {d.rows.map((r) => (
              <tr
                key={r.kpi}
                className={`border-t border-slate-100 ${r.is_need ? "bg-amber-50" : ""}`}
              >
                <th scope="row" className="py-2 pr-2 text-left font-normal">
                  <span className="flex flex-wrap items-center gap-1.5">
                    {r.label}
                    {r.is_proxy ? <ProxyBadge /> : null}
                    {r.is_need ? (
                      <span className="text-xs font-medium text-amber-900">(club need)</span>
                    ) : null}
                  </span>
                </th>
                <td className="pr-2">
                  <PercentileBar
                    label={`${d.a.player_name}: ${r.label}`}
                    percentile={r.a?.percentile}
                    detail={r.a ? formatPer90(r.a.value) : undefined}
                    showLabel={false}
                  />
                </td>
                <td className="pr-2">
                  <PercentileBar
                    label={`${d.b.player_name}: ${r.label}`}
                    percentile={r.b?.percentile}
                    detail={r.b ? formatPer90(r.b.value) : undefined}
                    tone="slate"
                    showLabel={false}
                  />
                </td>
                <td className="text-right font-semibold tabular-nums">{formatGap(r.delta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
