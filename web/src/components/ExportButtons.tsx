import { useState } from "react";

import { downloadReport, type ExportFormat } from "../api/download";
import type { SeasonMode } from "../lib/labels";

/** PDF and Markdown downloads of the grounded report, with its sources. */
export function ExportButtons({
  playerId,
  teamId,
  seasonMode,
}: {
  playerId: number;
  teamId: number | undefined;
  seasonMode: SeasonMode;
}) {
  const [status, setStatus] = useState("");
  function run(format: ExportFormat) {
    setStatus("Preparing the file…");
    downloadReport(playerId, format, { teamId, seasonMode }).then(
      (name) => {
        setStatus(`Saved ${name}.`);
      },
      () => {
        setStatus("Export failed; try again.");
      },
    );
  }
  const button =
    "rounded-md border border-slate-300 bg-white px-3 py-1 text-sm text-slate-800 hover:bg-slate-50 focus:ring-2 focus:ring-accent-600 focus:outline-none";
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button
        type="button"
        className={button}
        onClick={() => {
          run("pdf");
        }}
      >
        Download PDF
      </button>
      <button
        type="button"
        className={button}
        onClick={() => {
          run("markdown");
        }}
      >
        Download Markdown
      </button>
      <span role="status" className="text-xs text-slate-600">
        {status}
      </span>
    </span>
  );
}
