import { Link, useNavigate } from "react-router";

import type { Schemas } from "../api/client";
import { AnalysisControls } from "../components/AnalysisControls";
import { Badge, ProxyBadge } from "../components/Badges";
import { Card } from "../components/Card";
import { ClubPicker } from "../components/ClubPicker";
import { HeatStrip } from "../components/HeatStrip";
import { Receipt } from "../components/Receipt";
import { EmptyState, LoadingState, QueryError } from "../components/states";
import { useDiagnosis, useTeams } from "../hooks/teams";
import {
  formatDate,
  formatGap,
  formatMinutes,
  formatNumber,
  formatPer90,
  formatPercentile,
  formatShare,
} from "../lib/format";
import { RISK_KINDS, benchmarkLabel, positionLabel } from "../lib/labels";
import { analysisQuery, parseIntParam, useAnalysisParams } from "../lib/urlState";

type Diagnosis = Schemas["DiagnosisResponse"];
type Need = Schemas["NeedOut"];

const TOP_NEEDS = 3;

export function DiagnosisPage() {
  const { params, update, seasonMode, benchmark, custom } = useAnalysisParams();
  const teamId = parseIntParam(params.get("team"));
  const teams = useTeams();
  const diagnosis = useDiagnosis(teamId, { seasonMode, benchmark, custom });

  return (
    <div className="space-y-6">
      <header className="space-y-4">
        <h1 className="text-2xl font-semibold text-slate-900">Club diagnosis</h1>
        <div className="grid gap-4 md:grid-cols-[minmax(16rem,22rem)_1fr] md:items-end">
          <ClubPicker
            label={teamId === undefined ? "Pick a club" : "Change club"}
            onSelect={(hit) => {
              update({ team: hit.team_id });
            }}
          />
          <AnalysisControls
            seasonMode={seasonMode}
            benchmark={benchmark}
            custom={custom}
            teams={teams.data}
            excludeTeamId={teamId}
            onChange={(c) => {
              update({ mode: c.mode, benchmark: c.benchmark, custom: c.custom });
            }}
          />
        </div>
      </header>
      {teamId === undefined ? (
        <EmptyState title="Pick a club to start">
          Type a club name or nickname above. The engine compares its squad with the benchmark and
          ranks the position groups that need help most.
        </EmptyState>
      ) : benchmark === "custom" && custom.length === 0 ? (
        <EmptyState title="Choose the custom benchmark clubs">
          Tick at least one club to compare against.
        </EmptyState>
      ) : diagnosis.isPending ? (
        <LoadingState label="Diagnosing the squad…" />
      ) : diagnosis.isError ? (
        <QueryError
          error={diagnosis.error}
          onRetry={() => {
            void diagnosis.refetch();
          }}
        />
      ) : (
        <DiagnosisView diagnosis={diagnosis.data} />
      )}
    </div>
  );
}

function shortlistLink(d: Diagnosis, need: Need, params: URLSearchParams): string {
  const q = params.toString();
  return `/clubs/${d.team_id}/needs/${need.need_id}${q ? `?${q}` : ""}`;
}

function DiagnosisView({ diagnosis: d }: { diagnosis: Diagnosis }) {
  const { seasonMode, benchmark, custom } = useAnalysisParams();
  const carry = analysisQuery(seasonMode, benchmark, custom);
  const ranked = d.needs.filter((n) => n.severity > 0);
  const top = ranked.slice(0, TOP_NEEDS);
  const weakLinks = d.needs.flatMap((n) =>
    n.weak_links.map((w) => ({ ...w, group: n.position_group })),
  );
  const risks = d.needs.flatMap((n) => n.risks.map((r) => ({ ...r, group: n.position_group })));
  const evidence = d.needs.flatMap((n) => n.evidence);
  const navigate = useNavigate();
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-700">
        <span className="text-lg font-semibold text-slate-900">{d.team_name}</span> compared with{" "}
        {benchmarkLabel(d.benchmark)} ({d.benchmark_teams.map((t) => t.name).join(", ")}) ·{" "}
        {d.current_season} ·{" "}
        {d.season_mode === "blended" ? "blended with last season" : "this season only"}
      </p>
      <Card title="Need severity by position group">
        <HeatStrip needs={d.needs} linkFor={(n) => shortlistLink(d, n, carry)} />
        <p className="mt-2 text-xs text-slate-600">
          Severity = Σ KPI weight × percentile points the club trails the benchmark by (0 = no
          shortfall). Click a group for its shortlist.
        </p>
      </Card>
      <section aria-labelledby="top-needs" className="space-y-4">
        <h2 id="top-needs" className="text-lg font-semibold text-slate-900">
          Top needs
        </h2>
        {top.length === 0 ? (
          <EmptyState title="No shortfalls against this benchmark">
            {d.team_name} match or beat the benchmark on every weighted KPI.
          </EmptyState>
        ) : (
          top.map((need) => (
            <NeedCard
              key={need.need_id}
              need={need}
              teamNeeds={d.team_needs.filter((t) => need.team_needs.includes(t.kpi))}
              onShortlist={() => {
                void navigate(shortlistLink(d, need, carry));
              }}
            />
          ))
        )}
      </section>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card
          title="Weak links"
          footer={<Receipt items={evidence.map((e) => ({ source: e.source, asOf: e.as_of }))} />}
        >
          {weakLinks.length === 0 ? (
            <p className="text-sm text-slate-600">
              No regular starter rates below the weak-link threshold on a key KPI.
            </p>
          ) : (
            <ul className="space-y-1 text-sm">
              {weakLinks.map((w) => (
                <li key={`${String(w.player_id)}-${w.kpi}`}>
                  <Link
                    className="font-medium text-accent-800 underline"
                    to={`/players/${w.player_id}?${carry.toString()}`}
                  >
                    {w.player_name}
                  </Link>{" "}
                  ({w.group}) · {w.label}: {formatPercentile(w.percentile)} ·{" "}
                  {formatShare(w.minutes_share)} of minutes
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Squad risks">
          {risks.length === 0 ? (
            <p className="text-sm text-slate-600">No depth, age or contract risk flagged.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {risks.map((r, i) => (
                <li key={`${r.group}-${r.kind}-${String(i)}`}>
                  <Badge tone="warn">{RISK_KINDS[r.kind] ?? r.kind}</Badge> {r.group}:{" "}
                  {r.player_name ? `${r.player_name}, ` : ""}
                  {r.detail}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <Card
        title="Team-level needs"
        footer={<Receipt items={d.team_needs.map((t) => ({ source: t.source, asOf: t.as_of }))} />}
      >
        {d.team_needs.length === 0 ? (
          <p className="text-sm text-slate-600">No team-level shortfall, or no team data yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Team KPIs where the club trails the benchmark</caption>
            <thead className="text-xs text-slate-600">
              <tr>
                <th scope="col" className="py-1">
                  KPI
                </th>
                <th scope="col">Club</th>
                <th scope="col">Benchmark</th>
                <th scope="col">Gap</th>
                <th scope="col">Groups</th>
                <th scope="col">Matches</th>
              </tr>
            </thead>
            <tbody>
              {d.team_needs.map((t) => (
                <tr key={t.kpi} className="border-t border-slate-100">
                  <td className="py-1">{t.label}</td>
                  <td className="tabular-nums">
                    {formatNumber(t.club_value, 2)} ({formatPercentile(t.club_percentile)})
                  </td>
                  <td className="tabular-nums">
                    {formatNumber(t.benchmark_value, 2)} ({formatPercentile(t.benchmark_percentile)}
                    )
                  </td>
                  <td className="tabular-nums">{formatGap(t.gap)}</td>
                  <td>{t.responsible_groups.join(", ")}</td>
                  <td className="tabular-nums">
                    {t.matches} + {t.previous_matches} last season
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function NeedCard({
  need,
  teamNeeds,
  onShortlist,
}: {
  need: Need;
  teamNeeds: Schemas["TeamNeedOut"][];
  onShortlist: () => void;
}) {
  const gaps = need.gaps
    .filter((g) => g.gap !== null)
    .sort((a, b) => (b.gap ?? 0) * b.weight - (a.gap ?? 0) * a.weight);
  return (
    <Card
      headingLevel={3}
      title={
        <>
          #{need.rank} {positionLabel(need.position_group)} ({need.position_group}) · severity{" "}
          {formatNumber(need.severity)}
        </>
      }
      actions={
        <button
          type="button"
          onClick={onShortlist}
          className="rounded-md bg-accent-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-800 focus:ring-2 focus:ring-accent-600 focus:ring-offset-2 focus:outline-none"
        >
          Find players for this need
        </button>
      }
      footer={<Receipt items={need.evidence.map((e) => ({ source: e.source, asOf: e.as_of }))} />}
    >
      <table className="w-full text-left text-sm">
        <caption className="sr-only">
          Club vs benchmark percentile scores for {need.position_group}
        </caption>
        <thead className="text-xs text-slate-600">
          <tr>
            <th scope="col" className="py-1">
              KPI
            </th>
            <th scope="col">Weight</th>
            <th scope="col">Club</th>
            <th scope="col">Benchmark</th>
            <th scope="col">Gap</th>
          </tr>
        </thead>
        <tbody>
          {gaps.map((g) => (
            <tr key={g.kpi} className="border-t border-slate-100">
              <td className="py-1">
                <span className="flex items-center gap-1.5">
                  {g.label}
                  {g.is_proxy ? <ProxyBadge /> : null}
                </span>
              </td>
              <td className="tabular-nums">{formatShare(g.weight)}</td>
              <td className="tabular-nums">{formatPercentile(g.club_score)}</td>
              <td className="tabular-nums">{formatPercentile(g.benchmark_score)}</td>
              <td
                className={`tabular-nums ${(g.gap ?? 0) > 0 ? "font-semibold text-amber-900" : ""}`}
              >
                {formatGap(g.gap)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {teamNeeds.length > 0 ? (
        <p className="mt-2 text-sm text-slate-700">
          Team-level shortfalls this group shares: {teamNeeds.map((t) => t.label).join("; ")}.
        </p>
      ) : null}
      {need.weak_links.length > 0 ? (
        <p className="mt-2 text-sm text-slate-700">
          Weak links:{" "}
          {need.weak_links
            .map((w) => `${w.player_name} (${w.label}, ${formatPercentile(w.percentile)})`)
            .join("; ")}
          .
        </p>
      ) : null}
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-accent-800">
          Evidence ({need.evidence.length} numbers)
        </summary>
        <table className="mt-2 w-full text-left text-xs">
          <caption className="sr-only">
            Player evidence behind the {need.position_group} need
          </caption>
          <thead className="text-slate-600">
            <tr>
              <th scope="col">Player</th>
              <th scope="col">KPI</th>
              <th scope="col">Per 90 (rated)</th>
              <th scope="col">Per 90 (this season)</th>
              <th scope="col">Percentile</th>
              <th scope="col">Peers</th>
              <th scope="col">Minutes</th>
              <th scope="col">Source · as of</th>
            </tr>
          </thead>
          <tbody>
            {need.evidence.map((e) => (
              <tr key={`${String(e.player_id)}-${e.kpi}`} className="border-t border-slate-100">
                <td>{e.player_name}</td>
                <td>
                  {e.label}
                  {e.padj_status === "unadjusted" ? (
                    <span className="ml-1">
                      <Badge tone="warn">unadjusted</Badge>
                    </span>
                  ) : null}
                </td>
                <td className="tabular-nums">{formatPer90(e.value)}</td>
                <td className="tabular-nums">{formatPer90(e.raw_p90)}</td>
                <td className="tabular-nums">{formatPercentile(e.percentile)}</td>
                <td className="tabular-nums">{e.n_peers}</td>
                <td className="tabular-nums">{formatMinutes(e.minutes)}</td>
                <td>
                  {e.source} · {formatDate(e.as_of)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </Card>
  );
}
