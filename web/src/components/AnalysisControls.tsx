import { useId } from "react";

import type { Schemas } from "../api/client";
import { BENCHMARKS, SEASON_MODES, type BenchmarkValue, type SeasonMode } from "../lib/labels";

/** Season mode (US-12) and benchmark (US-13) toggles; values live in the URL. */
export function AnalysisControls({
  seasonMode,
  benchmark,
  custom,
  teams,
  excludeTeamId,
  onChange,
  showBenchmark = true,
}: {
  seasonMode: SeasonMode;
  benchmark: BenchmarkValue;
  custom: number[];
  teams?: Schemas["TeamOut"][] | undefined;
  excludeTeamId?: number | undefined;
  onChange: (changes: { mode?: SeasonMode; benchmark?: BenchmarkValue; custom?: number[] }) => void;
  showBenchmark?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex flex-wrap items-end gap-4">
      <fieldset>
        <legend className="text-sm font-medium text-slate-700">Season data</legend>
        <div className="mt-1 inline-flex rounded-md border border-slate-300 bg-white p-0.5">
          {SEASON_MODES.map((m) => (
            <label
              key={m.value}
              className={`cursor-pointer rounded px-2.5 py-1 text-sm focus-within:ring-2 focus-within:ring-accent-600 ${seasonMode === m.value ? "bg-accent-700 text-white" : "text-slate-700"}`}
            >
              <input
                type="radio"
                name={`${id}-mode`}
                value={m.value}
                checked={seasonMode === m.value}
                onChange={() => {
                  onChange({ mode: m.value });
                }}
                className="sr-only"
              />
              {m.label}
            </label>
          ))}
        </div>
      </fieldset>
      {showBenchmark ? (
        <div>
          <label htmlFor={`${id}-benchmark`} className="block text-sm font-medium text-slate-700">
            Benchmark
          </label>
          <select
            id={`${id}-benchmark`}
            value={benchmark}
            onChange={(event) => {
              onChange({ benchmark: event.target.value as BenchmarkValue });
            }}
            className="mt-1 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm focus:ring-2 focus:ring-accent-600 focus:outline-none"
          >
            {BENCHMARKS.map((b) => (
              <option key={b.value} value={b.value}>
                {b.label}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {showBenchmark && benchmark === "custom" ? (
        <fieldset className="w-full">
          <legend className="text-sm font-medium text-slate-700">Custom benchmark clubs</legend>
          {teams ? (
            <div className="mt-1 grid grid-cols-2 gap-1 sm:grid-cols-4">
              {teams
                .filter((t) => t.team_id !== excludeTeamId)
                .map((t) => (
                  <label
                    key={t.team_id}
                    className="flex items-center gap-1.5 text-sm text-slate-800"
                  >
                    <input
                      type="checkbox"
                      checked={custom.includes(t.team_id)}
                      onChange={(event) => {
                        onChange({
                          custom: event.target.checked
                            ? [...custom, t.team_id].sort((a, b) => a - b)
                            : custom.filter((c) => c !== t.team_id),
                        });
                      }}
                    />
                    {t.name}
                  </label>
                ))}
            </div>
          ) : (
            <p className="text-sm text-slate-600">Loading clubs…</p>
          )}
          {custom.length === 0 ? (
            <p className="mt-1 text-sm text-amber-900">
              Pick at least one club to compare against.
            </p>
          ) : null}
        </fieldset>
      ) : null}
    </div>
  );
}
