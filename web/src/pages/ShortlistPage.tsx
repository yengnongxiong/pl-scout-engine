import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { Fragment, lazy, Suspense, useMemo, useState, type SubmitEvent } from "react";
import { Link, useParams } from "react-router";

import type { Schemas } from "../api/client";
import { AnalysisControls } from "../components/AnalysisControls";
import { GateBadge, ProxyBadge, StaleBadge, ValueLabelBadge } from "../components/Badges";
import { Card } from "../components/Card";
import { FitBreakdown } from "../components/FitBreakdown";
import { PercentileBar } from "../components/PercentileBar";
import { Receipt } from "../components/Receipt";
import { EmptyState, LoadingState, QueryError } from "../components/states";
import { useShortlist, useTeams } from "../hooks/teams";
import {
  NOT_AVAILABLE,
  formatAge,
  formatDate,
  formatEurMillions,
  formatInteger,
  formatMinutes,
  formatPeers,
  formatPer90,
  formatScore,
} from "../lib/format";
import { positionLabel, statusLabel } from "../lib/labels";
import {
  analysisQuery,
  parseIdList,
  parseIntParam,
  parseNumberParam,
  useAnalysisParams,
} from "../lib/urlState";

type Shortlist = Schemas["ShortlistResponse"];
type Candidate = Schemas["CandidateOut"];

const EUR_PER_MILLION = 1_000_000;

// Recharts is only needed for the Moneyball view; load it on demand.
const MoneyballChart = lazy(() =>
  import("../components/MoneyballChart").then((m) => ({ default: m.MoneyballChart })),
);

export function ShortlistPage() {
  const { teamId: teamParam, needId } = useParams();
  const teamId = parseIntParam(teamParam ?? null);
  const { params, update, seasonMode, benchmark, custom } = useAnalysisParams();
  const teams = useTeams();
  const maxValueM = parseNumberParam(params.get("maxValue"));
  const filters = {
    maxValueEur: maxValueM === undefined ? undefined : Math.round(maxValueM * EUR_PER_MILLION),
    minAge: parseNumberParam(params.get("minAge")),
    maxAge: parseNumberParam(params.get("maxAge")),
    minMinutes: parseNumberParam(params.get("minMinutes")),
    excludeTeamIds: parseIdList(params.get("exclude")),
    includeSideways: params.get("sideways") === "1",
  };
  const moneyball = params.get("moneyball") === "1";
  const shortlist = useShortlist(teamId, needId, { seasonMode, benchmark, custom }, filters);
  const carry = analysisQuery(seasonMode, benchmark, custom);
  const group = needId?.split("-")[1];

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <p className="text-sm">
          <Link
            to={`/?${new URLSearchParams([...carry.entries(), ["team", String(teamId ?? "")]]).toString()}`}
            className="text-accent-800 underline"
          >
            ← Back to the club diagnosis
          </Link>
        </p>
        <h1 className="text-2xl font-semibold text-slate-900">
          Shortlist: {shortlist.data?.team_name ?? "club"} · {positionLabel(group)}
        </h1>
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
      </header>
      <FiltersForm
        teams={teams.data ?? []}
        clubId={teamId}
        initial={{
          maxValue: maxValueM,
          minAge: filters.minAge,
          maxAge: filters.maxAge,
          minMinutes: filters.minMinutes,
          exclude: filters.excludeTeamIds,
          sideways: filters.includeSideways,
        }}
        onApply={(f) => {
          update({
            maxValue: f.maxValue,
            minAge: f.minAge,
            maxAge: f.maxAge,
            minMinutes: f.minMinutes,
            exclude: f.exclude,
            sideways: f.sideways,
          });
        }}
      />
      <label className="flex items-center gap-2 text-sm text-slate-800">
        <input
          type="checkbox"
          checked={moneyball}
          onChange={(event) => {
            update({ moneyball: event.target.checked });
          }}
        />
        Moneyball view: compare the Transfermarkt estimated market value with the stats-implied
        value
      </label>
      {teamId === undefined || needId === undefined ? (
        <EmptyState title="Not available">This link does not name a club and need.</EmptyState>
      ) : shortlist.isPending ? (
        <LoadingState label="Scoring candidates…" />
      ) : shortlist.isError ? (
        <QueryError
          error={shortlist.error}
          onRetry={() => {
            void shortlist.refetch();
          }}
        />
      ) : (
        <ShortlistView shortlist={shortlist.data} moneyball={moneyball} carry={carry} />
      )}
    </div>
  );
}

interface FilterValues {
  maxValue: number | undefined;
  minAge: number | undefined;
  maxAge: number | undefined;
  minMinutes: number | undefined;
  exclude: number[];
  sideways: boolean;
}

function numberOrUndefined(form: FormData, name: string): number | undefined {
  const raw = form.get(name);
  if (typeof raw !== "string" || raw.trim() === "") {
    return undefined;
  }
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

function FiltersForm({
  teams,
  clubId,
  initial,
  onApply,
}: {
  teams: Schemas["TeamOut"][];
  clubId: number | undefined;
  initial: FilterValues;
  onApply: (values: FilterValues) => void;
}) {
  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    onApply({
      maxValue: numberOrUndefined(form, "maxValue"),
      minAge: numberOrUndefined(form, "minAge"),
      maxAge: numberOrUndefined(form, "maxAge"),
      minMinutes: numberOrUndefined(form, "minMinutes"),
      exclude: form
        .getAll("exclude")
        .map((v) => Number(v))
        .filter((n) => Number.isInteger(n)),
      sideways: form.get("sideways") === "on",
    });
  }
  const field =
    "mt-1 w-28 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:ring-2 focus:ring-accent-600 focus:outline-none";
  return (
    <form
      onSubmit={submit}
      aria-label="Shortlist filters"
      className="flex flex-wrap items-end gap-4 rounded-lg border border-slate-200 bg-white p-4"
      key={JSON.stringify(initial)}
    >
      <label className="text-sm text-slate-700">
        Max value (€m)
        <input
          name="maxValue"
          type="number"
          min="0"
          step="0.5"
          defaultValue={initial.maxValue}
          className={`block ${field}`}
        />
      </label>
      <label className="text-sm text-slate-700">
        Min age
        <input
          name="minAge"
          type="number"
          min="15"
          max="45"
          defaultValue={initial.minAge}
          className={`block ${field}`}
        />
      </label>
      <label className="text-sm text-slate-700">
        Max age
        <input
          name="maxAge"
          type="number"
          min="15"
          max="45"
          defaultValue={initial.maxAge}
          className={`block ${field}`}
        />
      </label>
      <label className="text-sm text-slate-700">
        Min minutes
        <input
          name="minMinutes"
          type="number"
          min="0"
          step="90"
          defaultValue={initial.minMinutes}
          className={`block ${field}`}
        />
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input name="sideways" type="checkbox" defaultChecked={initial.sideways} />
        Include sideways moves
      </label>
      <details className="text-sm">
        <summary className="cursor-pointer text-accent-800">
          Exclude clubs ({initial.exclude.length})
        </summary>
        <div className="mt-2 grid grid-cols-2 gap-1 sm:grid-cols-3">
          {teams
            .filter((t) => t.team_id !== clubId)
            .map((t) => (
              <label key={t.team_id} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  name="exclude"
                  value={t.team_id}
                  defaultChecked={initial.exclude.includes(t.team_id)}
                />
                {t.name}
              </label>
            ))}
        </div>
      </details>
      <button
        type="submit"
        className="rounded-md bg-accent-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-800 focus:ring-2 focus:ring-accent-600 focus:ring-offset-2 focus:outline-none"
      >
        Apply filters
      </button>
    </form>
  );
}

const columns = createColumnHelper<Candidate>();

function ShortlistView({
  shortlist: s,
  moneyball,
  carry,
}: {
  shortlist: Shortlist;
  moneyball: boolean;
  carry: URLSearchParams;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [onlyUndervalued, setOnlyUndervalued] = useState(false);
  const data = useMemo(
    () =>
      moneyball && onlyUndervalued
        ? s.candidates.filter((c) => c.implied_value?.label === "Undervalued")
        : s.candidates,
    [s.candidates, moneyball, onlyUndervalued],
  );
  const playerQuery = new URLSearchParams([...carry.entries(), ["team", String(s.team_id)]]);
  const playerQueryString = playerQuery.toString();
  const tableColumns = useMemo(
    () => [
      columns.accessor("rank", { header: "#", cell: (c) => c.getValue() }),
      columns.accessor("player_name", {
        header: "Player",
        cell: (c) => (
          <Link
            to={`/players/${c.row.original.player_id}?${playerQueryString}`}
            className="font-medium text-accent-800 underline"
          >
            {c.getValue()}
          </Link>
        ),
      }),
      columns.accessor("team_name", { header: "Club" }),
      columns.accessor("age", { header: "Age", cell: (c) => formatAge(c.getValue()) }),
      columns.accessor("minutes", {
        header: "Minutes",
        cell: (c) => formatInteger(c.getValue()),
      }),
      columns.accessor("fpl_status", {
        header: "Availability",
        cell: (c) => statusLabel(c.getValue()),
        enableSorting: false,
      }),
      columns.accessor((c) => c.market_value?.value_eur ?? null, {
        id: "value",
        header: "TM value",
        cell: (c) => {
          const mv = c.row.original.market_value;
          return mv ? (
            <span>
              {formatEurMillions(mv.value_eur)}{" "}
              <span className="text-xs text-slate-600">({formatDate(mv.tm_last_updated)})</span>{" "}
              {mv.is_stale ? <StaleBadge /> : null}
            </span>
          ) : (
            NOT_AVAILABLE
          );
        },
        sortUndefined: "last",
      }),
      ...(moneyball
        ? [
            columns.accessor((c) => c.implied_value?.implied_value_eur ?? null, {
              id: "implied",
              header: "Stats-implied",
              cell: (c) => {
                const iv = c.row.original.implied_value;
                return iv ? (
                  <span>
                    {formatEurMillions(iv.implied_value_eur)}{" "}
                    <span className="text-xs text-slate-600">
                      ({formatEurMillions(iv.band_low_eur)}–{formatEurMillions(iv.band_high_eur)})
                    </span>{" "}
                    <ValueLabelBadge label={iv.label} />
                  </span>
                ) : (
                  NOT_AVAILABLE
                );
              },
            }),
          ]
        : []),
      columns.accessor((c) => c.fit.total ?? null, {
        id: "fit",
        header: "FitScore",
        cell: (c) => (
          <span className="font-semibold tabular-nums">{formatScore(c.getValue())}</span>
        ),
      }),
      columns.accessor("gate", {
        header: "Upgrade gate",
        cell: (c) => <GateBadge gate={c.getValue()} />,
        enableSorting: false,
      }),
    ],
    [moneyball, playerQueryString],
  );
  const table = useReactTable({
    data,
    columns: tableColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const excluded = Object.entries(s.excluded);
  const receipts = s.candidates.flatMap((c) => [
    ...c.evidence.map((e) => ({ source: e.source, asOf: e.as_of })),
    ...(c.market_value
      ? [{ source: c.market_value.source, asOf: c.market_value.tm_last_updated }]
      : []),
  ]);
  return (
    <div className="space-y-4">
      <Card title="The need">
        {s.caveat ? (
          <p className="mb-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">
            {s.caveat}
          </p>
        ) : null}
        <p className="text-sm text-slate-800">
          {s.team_name} trail the benchmark on:{" "}
          {s.deficits.length > 0
            ? s.deficits.map((d) => d.label).join("; ")
            : "nothing in this group, so NeedFill measures overall quality"}
          .
        </p>
        <p className="mt-1 text-sm text-slate-800">
          Incumbent (minutes leader):{" "}
          {s.incumbent ? (
            <>
              <Link
                to={`/players/${s.incumbent.player_id}?${playerQuery.toString()}`}
                className="text-accent-800 underline"
              >
                {s.incumbent.player_name}
              </Link>{" "}
              · {formatMinutes(s.incumbent.minutes)} · NeedFill {formatScore(s.incumbent.need_fill)}
            </>
          ) : (
            "none: the club has no minutes in this group yet"
          )}
        </p>
      </Card>
      {moneyball ? (
        <Card title="Moneyball view">
          <label className="mb-2 flex items-center gap-2 text-sm text-slate-800">
            <input
              type="checkbox"
              checked={onlyUndervalued}
              onChange={(event) => {
                setOnlyUndervalued(event.target.checked);
              }}
            />
            Only players the stats rate above their Transfermarkt estimated market value
          </label>
          <Suspense fallback={<LoadingState label="Loading chart…" />}>
            <MoneyballChart candidates={s.candidates} />
          </Suspense>
        </Card>
      ) : null}
      {excluded.length > 0 ? (
        <p className="text-sm text-slate-700">
          Filtered out: {excluded.map(([reason, n]) => `${reason} ${String(n)}`).join(", ")}.
        </p>
      ) : null}
      {data.length === 0 ? (
        <EmptyState title="No candidates">
          Nobody passes the filters for this need. Loosen the filters or include sideways moves.
        </EmptyState>
      ) : (
        <Card title={`Candidates (${String(data.length)})`} footer={<Receipt items={receipts} />}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">
                Shortlist ranked by FitScore; select a column header to sort
              </caption>
              <thead className="text-xs text-slate-600">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h) => {
                      const sorted = h.column.getIsSorted();
                      return (
                        <th
                          key={h.id}
                          scope="col"
                          className="py-2 pr-3"
                          aria-sort={
                            sorted === "asc"
                              ? "ascending"
                              : sorted === "desc"
                                ? "descending"
                                : undefined
                          }
                        >
                          {h.column.getCanSort() ? (
                            <button
                              type="button"
                              onClick={h.column.getToggleSortingHandler()}
                              className="font-medium hover:text-accent-800"
                            >
                              {flexRender(h.column.columnDef.header, h.getContext())}
                              {sorted === "asc" ? " ↑" : sorted === "desc" ? " ↓" : ""}
                            </button>
                          ) : (
                            flexRender(h.column.columnDef.header, h.getContext())
                          )}
                        </th>
                      );
                    })}
                    <th scope="col">
                      <span className="sr-only">Details</span>
                    </th>
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => {
                  const c = row.original;
                  const expanded = open === c.player_id;
                  return (
                    <Fragment key={row.id}>
                      <tr className="border-t border-slate-100 align-top">
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className="py-2 pr-3">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                        <td className="py-2">
                          <button
                            type="button"
                            aria-expanded={expanded}
                            onClick={() => {
                              setOpen(expanded ? null : c.player_id);
                            }}
                            className="text-accent-800 underline"
                          >
                            {expanded ? "Hide" : "Why?"}
                            <span className="sr-only"> {c.player_name}</span>
                          </button>
                        </td>
                      </tr>
                      {expanded ? (
                        <tr>
                          <td
                            colSpan={row.getVisibleCells().length + 1}
                            className="bg-slate-50 p-3"
                          >
                            <CandidateDetail
                              candidate={c}
                              shortlist={s}
                              playerQuery={playerQuery}
                            />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function CandidateDetail({
  candidate: c,
  shortlist: s,
  playerQuery,
}: {
  candidate: Candidate;
  shortlist: Shortlist;
  playerQuery: URLSearchParams;
}) {
  const need = new Set(s.deficits.map((d) => d.kpi));
  const compare = s.incumbent
    ? `/compare?a=${String(c.player_id)}&b=${String(s.incumbent.player_id)}&team=${String(s.team_id)}`
    : undefined;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <h4 className="mb-2 text-sm font-semibold text-slate-900">
          FitScore {formatScore(c.fit.total)} breakdown
        </h4>
        <FitBreakdown components={c.fit.components} weightsUsed={c.fit.weights_used} />
        <p className="mt-2 text-xs text-slate-600">
          Effective minutes {formatInteger(c.effective_minutes)}; availability{" "}
          {statusLabel(c.fpl_status)}
          {c.chance_of_playing !== null
            ? ` (${formatInteger(c.chance_of_playing)}% chance)`
            : ""}{" "}
          as of {formatDate(c.status_as_of)}.
        </p>
        <p className="mt-2 flex gap-3 text-sm">
          <Link
            to={`/players/${c.player_id}?${playerQuery.toString()}`}
            className="text-accent-800 underline"
          >
            Player page and report
          </Link>
          {compare ? (
            <Link to={compare} className="text-accent-800 underline">
              Compare with {s.incumbent?.player_name}
            </Link>
          ) : null}
        </p>
      </div>
      <div>
        <h4 className="mb-2 text-sm font-semibold text-slate-900">
          {positionLabel(c.position_group)} KPIs (percentile vs peers)
        </h4>
        {c.evidence.map((e) => (
          <PercentileBar
            key={e.kpi}
            label={e.label}
            percentile={e.percentile}
            detail={`${formatPer90(e.value)} · ${formatPeers(e.n_peers)}`}
            isProxy={e.is_proxy}
            highlight={need.has(e.kpi)}
          />
        ))}
        {c.evidence.some((e) => e.is_proxy) ? (
          <p className="mt-1 text-xs text-slate-600">
            <ProxyBadge /> marks a stand-in for data not freely available.
          </p>
        ) : null}
      </div>
    </div>
  );
}
