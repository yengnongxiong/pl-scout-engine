import { lazy, Suspense } from "react";

import { Badge, ProxyBadge } from "../components/Badges";
import { Card } from "../components/Card";
import { LoadingState, QueryError } from "../components/states";
import { useAgeCurves, useFreshness, useMethodology } from "../hooks/meta";
import {
  NOT_AVAILABLE,
  formatDateTime,
  formatInteger,
  formatNumber,
  formatShare,
} from "../lib/format";
import { FIT_COMPONENTS, positionLabel, sourceLabel } from "../lib/labels";

const AgeCurveChart = lazy(() =>
  import("../components/AgeCurveChart").then((m) => ({ default: m.AgeCurveChart })),
);

export function MethodologyPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Methodology &amp; data</h1>
      <FreshnessSection />
      <MethodologySection />
      <AgeCurvesSection />
    </div>
  );
}

function FreshnessSection() {
  const freshness = useFreshness();
  if (freshness.isPending) {
    return <LoadingState label="Checking data freshness…" />;
  }
  if (freshness.isError) {
    return (
      <QueryError
        error={freshness.error}
        onRetry={() => {
          void freshness.refetch();
        }}
      />
    );
  }
  const f = freshness.data;
  return (
    <Card title="Data freshness">
      <p className="text-sm text-slate-700">
        Warehouse built {formatDateTime(f.warehouse_version)} ·{" "}
        {f.validation_summary ?? "validation summary not available"} · FPL schema: {f.fpl_schema}
      </p>
      {f.sources.length === 0 ? (
        <p className="mt-2 text-sm text-slate-600">No snapshots yet: run `scout ingest`.</p>
      ) : (
        <table className="mt-3 w-full text-left text-sm">
          <caption className="sr-only">Newest snapshot per source</caption>
          <thead className="text-xs text-slate-600">
            <tr>
              <th scope="col">Source</th>
              <th scope="col">Last fetched</th>
              <th scope="col">Age</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {f.sources.map((s) => (
              <tr key={s.source} className="border-t border-slate-100">
                <td className="py-1">{sourceLabel(s.source)}</td>
                <td>{formatDateTime(s.last_fetched)}</td>
                <td className="tabular-nums">{formatInteger(s.age_hours)} h</td>
                <td>
                  {s.stale ? <Badge tone="warn">stale</Badge> : <Badge tone="good">fresh</Badge>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-3 text-sm text-slate-700">
        Players mapped across sources (share of FPL minutes):{" "}
        {Object.keys(f.coverage).length === 0
          ? NOT_AVAILABLE
          : Object.entries(f.coverage)
              .map(([source, share]) => `${sourceLabel(source)} ${formatShare(share)}`)
              .join(" · ")}
        . Records waiting for review: {formatInteger(f.review_count)}.
      </p>
      {f.warnings.length > 0 ? (
        <ul className="mt-2 list-disc pl-5 text-sm text-amber-900">
          {f.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

function MethodologySection() {
  const methodology = useMethodology();
  if (methodology.isPending) {
    return <LoadingState label="Loading definitions…" />;
  }
  if (methodology.isError) {
    return (
      <QueryError
        error={methodology.error}
        onRetry={() => {
          void methodology.refetch();
        }}
      />
    );
  }
  const m = methodology.data;
  const groups = Object.entries(m.position_groups);
  return (
    <div className="space-y-6">
      <Card title="Player KPIs">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">KPI definitions and weights per position group</caption>
            <thead className="text-xs text-slate-600">
              <tr>
                <th scope="col" className="py-1">
                  KPI
                </th>
                <th scope="col">Source</th>
                <th scope="col">Better</th>
                {groups.map(([g]) => (
                  <th scope="col" key={g} title={positionLabel(g)}>
                    {g}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {m.kpis.map((k) => (
                <tr key={k.kpi} className="border-t border-slate-100 align-top">
                  <td className="py-1 pr-2">
                    <span className="flex flex-wrap items-center gap-1.5">
                      {k.label}
                      {k.is_proxy ? <ProxyBadge proxyFor={k.proxy_for} /> : null}
                      {k.possession_adjusted ? <Badge>possession-adjusted</Badge> : null}
                    </span>
                    {k.is_proxy && k.proxy_for ? (
                      <span className="block text-xs text-slate-600">
                        Stands in for {k.proxy_for}.
                      </span>
                    ) : null}
                  </td>
                  <td>{sourceLabel(k.source)}</td>
                  <td>{k.higher_is_better ? "higher" : "lower"}</td>
                  {groups.map(([g, weights]) => (
                    <td key={g} className="tabular-nums">
                      {weights[k.kpi] !== undefined ? formatShare(weights[k.kpi]) : "–"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {Object.entries(m.group_caveats).map(([group, caveat]) => (
          <p
            key={group}
            className="mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900"
          >
            {positionLabel(group)}: {caveat}
          </p>
        ))}
        <p className="mt-2 text-xs text-slate-600">
          Weights per position group sum to 100%. Percentiles rank shrunk per-90 rates among players
          with at least {formatInteger(Number(m.parameters.percentile_min_minutes))} blended
          minutes, and always show the number of peers.
        </p>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="FitScore">
          <ul className="space-y-1 text-sm text-slate-800">
            {Object.entries(m.fit_weights).map(([name, weight]) => (
              <li key={name}>
                <span className="font-medium">{FIT_COMPONENTS[name]?.label ?? name}</span>{" "}
                {formatShare(weight)}: {FIT_COMPONENTS[name]?.help}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-sm text-slate-700">
            Upgrade gate: a candidate must beat the incumbent on NeedFill by at least{" "}
            {formatInteger(m.upgrade_gate_min_delta)} percentile points.
          </p>
          <p className="mt-2 text-sm text-slate-700">
            Peak-age windows:{" "}
            {Object.entries(m.peak_age)
              .map(([g, [lo, hi]]) => `${g} ${String(lo)}–${String(hi)}`)
              .join(", ")}
            .
          </p>
        </Card>
        <Card title="Thresholds">
          <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
            {Object.entries(m.parameters).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-slate-700">{key.replaceAll("_", " ")}</dt>
                <dd className="text-right text-slate-900 tabular-nums">
                  {typeof value === "number"
                    ? formatNumber(value, Number.isInteger(value) ? 0 : 2)
                    : value}
                </dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>
      <Card title="Team KPIs">
        <ul className="space-y-1 text-sm text-slate-800">
          {m.team_kpis.map((t) => (
            <li key={t.kpi}>
              {t.label} ({sourceLabel(t.source)}; {t.higher_is_better ? "higher" : "lower"} is
              better) → {t.responsible_groups.join(", ")}
            </li>
          ))}
        </ul>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Models">
          <ul className="space-y-1 text-sm text-slate-800">
            {m.models.map((run) => (
              <li key={run.name}>
                {run.name}:{" "}
                {run.trained_at
                  ? `trained ${formatDateTime(run.trained_at)} (commit ${run.git_sha ?? NOT_AVAILABLE}), ${formatInteger(run.rows)} players`
                  : "not trained yet (run `scout train`)"}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-600">{m.value_model_caveat}</p>
        </Card>
        <Card title="Known limitations">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
            {m.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function AgeCurvesSection() {
  const ages = useAgeCurves();
  return (
    <Card title="Age curves">
      {ages.isPending ? (
        <LoadingState label="Building age curves…" />
      ) : ages.isError ? (
        <p className="text-sm text-slate-600">
          {NOT_AVAILABLE}: age curves need at least two past seasons of FPL history (
          <code>scout ingest --source vaastav</code>).
        </p>
      ) : (
        <>
          <p className="text-sm text-slate-700">
            How a per-90 rate typically changes from one season to the next at each age (delta
            method): {formatInteger(ages.data.pair_count)} player pairs from{" "}
            {ages.data.seasons.join(", ")}, both seasons with at least{" "}
            {formatInteger(ages.data.min_minutes)} minutes; ages with fewer than{" "}
            {formatInteger(ages.data.min_pairs)} pairs are not shown.
          </p>
          <Suspense fallback={<LoadingState label="Loading chart…" />}>
            <AgeCurveChart curves={ages.data.curves} />
          </Suspense>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Typical next-season change per age and stat</caption>
              <thead className="text-xs text-slate-600">
                <tr>
                  <th scope="col">Age</th>
                  {ages.data.curves.map((c) => (
                    <th scope="col" key={c.metric}>
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(ages.data.curves[0]?.points ?? []).map((point, row) => (
                  <tr key={point.age} className="border-t border-slate-100">
                    <th scope="row" className="py-1 text-left font-normal">
                      {point.age}
                    </th>
                    {ages.data.curves.map((c) => {
                      const p = c.points[row];
                      return (
                        <td key={c.metric} className="tabular-nums">
                          {p?.delta === null || p?.delta === undefined
                            ? NOT_AVAILABLE
                            : `${p.delta > 0 ? "+" : ""}${formatNumber(p.delta, 3)} (n=${formatInteger(p.n_pairs)})`}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-slate-600">
            {ages.data.caveat} FPL history · as of {formatDateTime(ages.data.history_as_of)}
          </p>
        </>
      )}
    </Card>
  );
}
