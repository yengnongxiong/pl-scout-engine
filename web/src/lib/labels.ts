/** Display names for codes the API returns (positions, gates, statuses, components). */

export const POSITION_GROUPS: Record<string, string> = {
  GK: "Goalkeeper",
  CB: "Centre-back",
  FB: "Full-back",
  DM: "Defensive midfield",
  CM: "Central midfield",
  AM: "Attacking midfield",
  W: "Winger",
  ST: "Striker",
};

export function positionLabel(group: string | null | undefined): string {
  if (!group) {
    return "Position not available";
  }
  return POSITION_GROUPS[group] ?? group;
}

export const SEASON_MODES = [
  { value: "blended", label: "This season + last (blended)" },
  { value: "current", label: "This season only" },
] as const;

export type SeasonMode = (typeof SEASON_MODES)[number]["value"];

export const BENCHMARKS = [
  { value: "top6", label: "Top 6 of last season" },
  { value: "top4", label: "Top 4 of last season" },
  { value: "league", label: "League average" },
  { value: "custom", label: "Custom clubs" },
] as const;

export type BenchmarkValue = (typeof BENCHMARKS)[number]["value"];

export function benchmarkLabel(value: string): string {
  return BENCHMARKS.find((b) => b.value === value)?.label ?? value;
}

export const GATES: Record<string, { label: string; tone: "good" | "neutral" | "warn" }> = {
  upgrade: { label: "Upgrade", tone: "good" },
  no_incumbent: { label: "Fills a gap (no incumbent)", tone: "good" },
  sideways: { label: "Sideways move", tone: "warn" },
  insufficient_data: { label: "Not enough data", tone: "neutral" },
};

export function gateLabel(gate: string): string {
  return GATES[gate]?.label ?? gate;
}

export const FIT_COMPONENTS: Record<string, { label: string; help: string }> = {
  need_fill: {
    label: "NeedFill",
    help: "Weighted percentile on the KPIs where the club trails the benchmark.",
  },
  role_quality: { label: "RoleQuality", help: "Overall position-weighted percentile." },
  reliability: { label: "Reliability", help: "Minutes volume and current availability (FPL)." },
  style_fit: {
    label: "StyleFit",
    help: "Similarity of the player's current team style to the target club's.",
  },
  age_profile: { label: "AgeProfile", help: "Distance from the peak-age window for the group." },
};

export const FIT_ORDER = ["need_fill", "role_quality", "reliability", "style_fit", "age_profile"];

export const FPL_STATUS: Record<string, string> = {
  a: "Available",
  d: "Doubtful",
  i: "Injured",
  s: "Suspended",
  u: "Unavailable (left the club)",
  n: "Not available (e.g. loan terms)",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) {
    return "Not available";
  }
  return FPL_STATUS[status] ?? status;
}

export const RISK_KINDS: Record<string, string> = {
  depth: "Depth",
  age: "Age",
  contract: "Contract",
};

export const SOURCES: Record<string, string> = {
  fpl: "FPL",
  understat: "Understat",
  fotmob: "FotMob",
  transfermarkt: "Transfermarkt",
  transfermarkt_datasets: "Transfermarkt (datasets snapshot)",
  override: "Manual override",
  vaastav: "FPL history (vaastav)",
  statsbomb: "StatsBomb open data",
};

export function sourceLabel(source: string): string {
  return SOURCES[source] ?? source;
}
