import type { SeasonMode } from "../lib/labels";
import { api, ApiError } from "./client";

export type ExportFormat = "pdf" | "markdown";

const FILENAME = /filename="([^"]+)"/;

/** Save a blob under `name` through a temporary link. */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

/** Download a grounded scouting report as PDF or Markdown (US-17). */
export async function downloadReport(
  playerId: number,
  format: ExportFormat,
  options: { teamId?: number | undefined; seasonMode: SeasonMode },
): Promise<string> {
  const { data, response } = await api.GET("/players/{player_id}/report/export", {
    params: {
      path: { player_id: playerId },
      query: { format, team_id: options.teamId, season_mode: options.seasonMode },
    },
    parseAs: "blob",
  });
  if (!response.ok || data === undefined) {
    throw new ApiError(
      response.status,
      "http_error",
      `Export failed (HTTP ${String(response.status)}).`,
    );
  }
  const name =
    FILENAME.exec(response.headers.get("content-disposition") ?? "")?.[1] ??
    `scouting-report.${format === "pdf" ? "pdf" : "md"}`;
  saveBlob(data, name);
  return name;
}
