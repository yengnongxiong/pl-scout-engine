import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";

import type { Schemas } from "../api/client";
import { AnalysisControls } from "../components/AnalysisControls";
import { Badge, StaleBadge, ValueLabelBadge } from "../components/Badges";
import { Card } from "../components/Card";
import { ClubPicker } from "../components/ClubPicker";
import { CopyButton } from "../components/CopyButton";
import { PercentileBar } from "../components/PercentileBar";
import { PlayerPicker } from "../components/PlayerPicker";
import { Receipt } from "../components/Receipt";
import { EmptyState, LoadingState, QueryError } from "../components/states";
import { usePlayer, usePlayerAgeCurve, useReport, useSimilar } from "../hooks/players";
import { useTeams } from "../hooks/teams";
import {
  NOT_AVAILABLE,
  formatAge,
  formatDate,
  formatDateTime,
  formatEurMillions,
  formatInteger,
  formatMinutes,
  formatPeers,
  formatPer90,
  formatSimilarity,
} from "../lib/format";
import { positionLabel, sourceLabel, statusLabel } from "../lib/labels";
import { parseIntParam, useAnalysisParams } from "../lib/urlState";

type Facts = Schemas["FactSheet"];

export function PlayerPage() {
  const { playerId: param } = useParams();
  const playerId = parseIntParam(param ?? null);
  const { params, update, seasonMode, benchmark, custom } = useAnalysisParams();
  const teamId = parseIntParam(params.get("team"));
  const player = usePlayer(playerId, seasonMode);
  return (
    <div className="space-y-6">
      {playerId === undefined ? (
        <EmptyState title="Not available">This link does not name a player.</EmptyState>
      ) : player.isPending ? (
        <LoadingState label="Loading the player…" />
      ) : player.isError ? (
        <QueryError
          error={player.error}
          onRetry={() => {
            void player.refetch();
          }}
        />
      ) : (
        <>
          <PlayerHeader facts={player.data} />
          <AnalysisControls
            seasonMode={seasonMode}
            benchmark={benchmark}
            custom={custom}
            showBenchmark={false}
            onChange={(c) => {
              update({ mode: c.mode });
            }}
          />
          <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
            <div className="space-y-6">
              <KpiCard facts={player.data} />
              <ReportCard playerId={playerId} teamId={teamId} />
            </div>
            <div className="space-y-6">
              <ValueCard facts={player.data} />
              <AgeCurveCard playerId={playerId} />
              <SimilarCard playerId={playerId} />
              <CompareCard playerId={playerId} teamId={teamId} />
              <NotesCard facts={player.data} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function PlayerHeader({ facts: f }: { facts: Facts }) {
  const mv = f.market_value;
  return (
    <header>
      <h1 className="text-2xl font-semibold text-slate-900">{f.player_name}</h1>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <Fact term="Club" value={f.team_name} />
        <Fact term="Position" value={`${positionLabel(f.position_group)} (${f.position_group})`} />
        <Fact term="Age" value={formatAge(f.age)} />
        <Fact
          term="Minutes"
          value={`${formatMinutes(f.minutes)} this season · ${formatInteger(f.effective_minutes)} effective`}
        />
        <Fact
          term="Availability (FPL)"
          value={`${statusLabel(f.fpl_status)}${f.chance_of_playing !== null ? `, ${formatInteger(f.chance_of_playing)}% chance` : ""} · as of ${formatDate(f.status_as_of)}`}
        />
        <Fact term="Contract expiry" value={formatDate(f.contract_expiry)} />
        <Fact
          term="Transfermarkt estimated market value"
          value={
            mv ? (
              <>
                {formatEurMillions(mv.value_eur)} · TM as of {formatDate(mv.tm_last_updated)} ·{" "}
                {sourceLabel(mv.source)} {mv.is_stale ? <StaleBadge /> : null}
              </>
            ) : (
              NOT_AVAILABLE
            )
          }
        />
        <Fact term="Role archetype" value={f.role ? f.role.label : NOT_AVAILABLE} />
      </dl>
    </header>
  );
}

function Fact({ term, value }: { term: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-600">{term}</dt>
      <dd className="text-slate-900">{value}</dd>
    </div>
  );
}

function KpiCard({ facts: f }: { facts: Facts }) {
  const strengths = new Set(f.strengths);
  const concerns = new Set(f.concerns);
  return (
    <Card
      title={`Percentiles vs ${positionLabel(f.position_group)} peers`}
      footer={<Receipt items={f.kpis.map((k) => ({ source: k.source, asOf: k.as_of }))} />}
    >
      <p className="mb-2 text-xs text-slate-600">
        {f.current_season}
        {f.previous_season ? ` blended with ${f.previous_season}` : ""} · per 90 minutes · rates
        shrunk toward the group average before ranking · the line marks the 50th percentile
      </p>
      {f.kpis.map((k) => (
        <PercentileBar
          key={k.kpi}
          label={k.label}
          percentile={k.percentile}
          detail={`${formatPer90(k.value)} · ${formatPeers(k.n_peers)}${k.weight === 0 ? " · not weighted" : ""}`}
          isProxy={k.is_proxy}
          proxyFor={k.proxy_for}
          tone={strengths.has(k.kpi) || concerns.has(k.kpi) ? "accent" : "slate"}
        />
      ))}
      {f.kpis.some((k) => k.padj_status === "unadjusted") ? (
        <p className="mt-2 text-xs text-amber-900">
          Some defensive numbers are not possession-adjusted (possession data missing).
        </p>
      ) : null}
    </Card>
  );
}

function ValueCard({ facts: f }: { facts: Facts }) {
  const iv = f.implied_value;
  return (
    <Card title="Value">
      {iv ? (
        <>
          <p className="text-sm text-slate-800">
            Stats-implied value {formatEurMillions(iv.implied_value_eur)} (band{" "}
            {formatEurMillions(iv.band_low_eur)} to {formatEurMillions(iv.band_high_eur)}) vs
            Transfermarkt estimated market value{" "}
            {f.market_value ? formatEurMillions(f.market_value.value_eur) : NOT_AVAILABLE}:{" "}
            <ValueLabelBadge label={iv.label} />
          </p>
          <p className="mt-2 text-xs text-slate-600">{iv.caveat}</p>
          <p className="mt-1 text-xs text-slate-600">
            Model trained {formatDateTime(iv.trained_at)} (commit {iv.git_sha}).
          </p>
        </>
      ) : (
        <p className="text-sm text-slate-600">
          Stats-implied value: {NOT_AVAILABLE} (needs a Transfermarkt value, enough minutes and a
          trained value model).
        </p>
      )}
    </Card>
  );
}

function AgeCurveCard({ playerId }: { playerId: number }) {
  const curve = usePlayerAgeCurve(playerId);
  return (
    <Card title="Age curve (next season)">
      {curve.isPending ? (
        <LoadingState label="Projecting…" />
      ) : curve.isError ? (
        <p className="text-sm text-slate-600">
          {NOT_AVAILABLE}: age curves need two past seasons of FPL history.
        </p>
      ) : (
        <>
          <table className="w-full text-left text-sm">
            <caption className="sr-only">
              Current blended rate, typical change at this age and projection per stat
            </caption>
            <thead className="text-xs text-slate-600">
              <tr>
                <th scope="col">Stat</th>
                <th scope="col">Now</th>
                <th scope="col">At age {curve.data.age ?? NOT_AVAILABLE}</th>
                <th scope="col">Next season</th>
              </tr>
            </thead>
            <tbody>
              {curve.data.projections.map((p) => (
                <tr key={p.metric} className="border-t border-slate-100">
                  <th scope="row" className="py-1 text-left font-normal">
                    {p.label}
                  </th>
                  <td className="tabular-nums">{formatPer90(p.current)}</td>
                  <td className="tabular-nums">
                    {p.delta === null
                      ? NOT_AVAILABLE
                      : `${p.delta > 0 ? "+" : ""}${formatPer90(p.delta)} (n=${String(p.n_pairs)})`}
                  </td>
                  <td className="tabular-nums">{formatPer90(p.projected)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-600">{curve.data.caveat}</p>
        </>
      )}
    </Card>
  );
}

function SimilarCard({ playerId }: { playerId: number }) {
  const similar = useSimilar(playerId, useAnalysisParams().seasonMode);
  return (
    <Card title="Similar players">
      {similar.isPending ? (
        <LoadingState label="Finding similar players…" />
      ) : similar.isError ? (
        <p className="text-sm text-slate-600">
          {NOT_AVAILABLE}: the player is not ranked on every KPI of the group yet.
        </p>
      ) : similar.data.results.length === 0 ? (
        <p className="text-sm text-slate-600">No other ranked player in this group.</p>
      ) : (
        <ol className="space-y-1 text-sm">
          {similar.data.results.map((s) => (
            <li key={s.player_id} className="flex justify-between gap-2">
              <Link to={`/players/${s.player_id}`} className="text-accent-800 underline">
                {s.player_name}
              </Link>
              <span className="text-slate-600 tabular-nums">
                {s.team_name ?? NOT_AVAILABLE} · cosine {formatSimilarity(s.similarity)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function ReportCard({ playerId, teamId }: { playerId: number; teamId: number | undefined }) {
  const { update, seasonMode } = useAnalysisParams();
  const teams = useTeams();
  const report = useReport(playerId, teamId, seasonMode);
  const club = teams.data?.find((t) => t.team_id === teamId);
  return (
    <Card
      title="Scouting report"
      actions={
        report.data ? <CopyButton text={report.data.report.text} label="Copy report" /> : null
      }
    >
      <div className="mb-3 grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
        <ClubPicker
          label={club ? `Fit against: ${club.name} (change)` : "Fit against a club (optional)"}
          onSelect={(hit) => {
            update({ team: hit.team_id });
          }}
        />
        {teamId !== undefined ? (
          <button
            type="button"
            onClick={() => {
              update({ team: undefined });
            }}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50"
          >
            Clear club
          </button>
        ) : null}
      </div>
      {report.isPending ? (
        <LoadingState label="Writing the report…" />
      ) : report.isError ? (
        <QueryError
          error={report.error}
          onRetry={() => {
            void report.refetch();
          }}
        />
      ) : (
        <>
          <pre className="max-h-[36rem] overflow-auto rounded bg-slate-50 p-3 font-mono text-xs whitespace-pre-wrap text-slate-900">
            {report.data.report.text}
          </pre>
          <p className="mt-2 text-xs text-slate-600">
            {report.data.report.engine === "ollama"
              ? "Rewritten by a local model and checked number by number against the fact sheet."
              : "Template report: every number comes from the fact sheet."}
            {report.data.report.fallback_reason ? (
              <>
                {" "}
                <Badge tone="warn">fallback</Badge> {report.data.report.fallback_reason}.
              </>
            ) : null}
          </p>
        </>
      )}
    </Card>
  );
}

function CompareCard({ playerId, teamId }: { playerId: number; teamId: number | undefined }) {
  const navigate = useNavigate();
  return (
    <Card title="Compare">
      <PlayerPicker
        label="Compare with"
        onSelect={(hit) => {
          const q = new URLSearchParams({ a: String(playerId), b: String(hit.player_id) });
          if (teamId !== undefined) {
            q.set("team", String(teamId));
          }
          void navigate(`/compare?${q.toString()}`);
        }}
      />
    </Card>
  );
}

function NotesCard({ facts: f }: { facts: Facts }) {
  return (
    <Card title="Data notes">
      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
        {f.caveats.map((c) => (
          <li key={c.kind}>{c.text}</li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-slate-600">
        Sources:{" "}
        {f.sources.map((s) => `${sourceLabel(s.source)} (as of ${formatDate(s.as_of)})`).join("; ")}
      </p>
    </Card>
  );
}
