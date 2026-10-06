/**
 * Synthetic API responses for front-end tests. Every name and number is made up and only
 * used by MSW handlers in tests (CLAUDE.md data integrity rule 1).
 */
import type { Schemas } from "../api/client";

const AS_OF = "2026-09-28T10:00:00+00:00";

export const teams: Schemas["TeamOut"][] = [
  { team_id: 1, name: "Synthetic Rovers", short_name: "SYR", aliases: ["Rovers"] },
  { team_id: 2, name: "Fixture Town", short_name: "FXT", aliases: [] },
  { team_id: 3, name: "Mock City", short_name: "MCK", aliases: ["The Mocks"] },
];

export function teamSearch(q: string): Schemas["TeamSearchHit"][] {
  const query = q.toLowerCase();
  if (query.startsWith("rov") || query === "synthetic") {
    return [{ team_id: 1, name: "Synthetic Rovers", matched: "Rovers", kind: "prefix", score: 90 }];
  }
  if (query === "mok cty") {
    return [{ team_id: 3, name: "Mock City", matched: "Mock City", kind: "fuzzy", score: 81 }];
  }
  return [];
}

function evidence(
  playerId: number,
  name: string,
  kpi: string,
  label: string,
  pct: number | null,
  extra: Partial<Schemas["EvidenceOut"]> = {},
): Schemas["EvidenceOut"] {
  return {
    player_id: playerId,
    player_name: name,
    kpi,
    label,
    raw_p90: 0.31,
    value: 0.29,
    percentile: pct,
    n_peers: 42,
    minutes: 610,
    source: "understat",
    as_of: AS_OF,
    is_proxy: false,
    padj_status: null,
    ...extra,
  };
}

const NPXG = "Non-penalty xG (per 90)";
const SHOTS = "Shots (per 90)";
const CHAIN = "Possession involvement (xGChain per 90)";

export const diagnosis: Schemas["DiagnosisResponse"] = {
  team_id: 1,
  team_name: "Synthetic Rovers",
  season_mode: "blended",
  current_season: "2026-27",
  benchmark: "top6",
  benchmark_teams: [
    { team_id: 2, name: "Fixture Town" },
    { team_id: 3, name: "Mock City" },
  ],
  needs: [
    {
      rank: 1,
      need_id: "1-ST",
      position_group: "ST",
      severity: 18.4,
      gaps: [
        {
          kpi: "npxg_p90",
          label: NPXG,
          weight: 0.4,
          is_proxy: false,
          club_score: 35,
          benchmark_score: 66,
          gap: 31,
        },
        {
          kpi: "xg_chain_p90",
          label: CHAIN,
          weight: 0.15,
          is_proxy: true,
          club_score: 40,
          benchmark_score: 52,
          gap: 12,
        },
        {
          kpi: "shots_p90",
          label: SHOTS,
          weight: 0.2,
          is_proxy: false,
          club_score: 70,
          benchmark_score: 61,
          gap: -9,
        },
      ],
      evidence: [
        evidence(7, "Ivo Placeholder", "npxg_p90", NPXG, 35),
        evidence(7, "Ivo Placeholder", "xg_chain_p90", CHAIN, 40, { is_proxy: true }),
      ],
      weak_links: [
        {
          player_id: 7,
          player_name: "Ivo Placeholder",
          kpi: "npxg_p90",
          label: NPXG,
          percentile: 22,
          minutes_share: 0.71,
        },
      ],
      risks: [
        {
          kind: "depth",
          detail: "one player has 92% of minutes and no backup rates above the 40th percentile",
          player_id: 7,
          player_name: "Ivo Placeholder",
          value: 0.92,
        },
      ],
      team_needs: ["xg_p90"],
    },
    {
      rank: 2,
      need_id: "1-CB",
      position_group: "CB",
      severity: 6.2,
      gaps: [
        {
          kpi: "cbi_padj_p90",
          label: "Clearances, blocks & interceptions, possession-adjusted (per 90)",
          weight: 0.2,
          is_proxy: false,
          club_score: 48,
          benchmark_score: 79,
          gap: 31,
        },
      ],
      evidence: [
        evidence(
          8,
          "Dee Fender",
          "cbi_padj_p90",
          "Clearances, blocks & interceptions, possession-adjusted (per 90)",
          48,
          { source: "fpl", padj_status: "unadjusted" },
        ),
      ],
      weak_links: [],
      risks: [],
      team_needs: [],
    },
    {
      rank: 3,
      need_id: "1-W",
      position_group: "W",
      severity: 0,
      gaps: [],
      evidence: [],
      weak_links: [],
      risks: [],
      team_needs: [],
    },
  ],
  team_needs: [
    {
      kpi: "xg_p90",
      label: "xG for (per 90)",
      higher_is_better: true,
      club_value: 1.12,
      club_percentile: 30,
      benchmark_value: 1.71,
      benchmark_percentile: 85,
      gap: 55,
      n_peers: 20,
      matches: 7,
      previous_matches: 38,
      responsible_groups: ["ST", "W", "AM"],
      source: "understat",
      as_of: AS_OF,
    },
  ],
};

export const diagnosisNoShortfall: Schemas["DiagnosisResponse"] = {
  ...diagnosis,
  needs: diagnosis.needs.map((n) => ({ ...n, severity: 0, weak_links: [], risks: [] })),
  team_needs: [],
};

const fit = (total: number, needFill: number): Schemas["FitOut"] => ({
  total,
  components: {
    need_fill: needFill,
    role_quality: 71.5,
    reliability: 88,
    style_fit: null,
    age_profile: 100,
  },
  weights_used: { need_fill: 0.44, role_quality: 0.28, reliability: 0.17, age_profile: 0.11 },
});

export const shortlist: Schemas["ShortlistResponse"] = {
  team_id: 1,
  team_name: "Synthetic Rovers",
  need_id: "1-ST",
  position_group: "ST",
  season_mode: "blended",
  deficits: [{ kpi: "npxg_p90", label: NPXG, weight: 12.4 }],
  incumbent: { player_id: 7, player_name: "Ivo Placeholder", minutes: 610, need_fill: 35 },
  candidates: [
    {
      rank: 1,
      player_id: 11,
      player_name: "Sam Synthetic",
      team_id: 2,
      team_name: "Fixture Town",
      position_group: "ST",
      age: 27.5,
      minutes: 540,
      effective_minutes: 1540,
      fpl_status: "a",
      chance_of_playing: null,
      status_as_of: AS_OF,
      market_value: {
        value_eur: 38_000_000,
        tm_last_updated: "2026-09-15",
        source: "transfermarkt",
        is_stale: false,
      },
      implied_value: {
        implied_value_eur: 52_400_000,
        band_low_eur: 41_000_000,
        band_high_eur: 66_000_000,
        label: "Undervalued",
        trained_at: AS_OF,
        git_sha: "abc1234",
        caveat: "Stats-implied value, not a fee prediction.",
      },
      fit: fit(78.4, 93),
      gate: "upgrade",
      evidence: [
        evidence(11, "Sam Synthetic", "npxg_p90", NPXG, 93),
        evidence(11, "Sam Synthetic", "xg_chain_p90", CHAIN, null, { is_proxy: true }),
      ],
    },
    {
      rank: 2,
      player_id: 12,
      player_name: "Alex Example",
      team_id: 3,
      team_name: "Mock City",
      position_group: "ST",
      age: 31.2,
      minutes: 380,
      effective_minutes: 1900,
      fpl_status: "d",
      chance_of_playing: 75,
      status_as_of: AS_OF,
      market_value: {
        value_eur: 12_500_000,
        tm_last_updated: "2026-06-30",
        source: "transfermarkt_datasets",
        is_stale: true,
      },
      implied_value: null,
      fit: fit(64.1, 71),
      gate: "upgrade",
      evidence: [evidence(12, "Alex Example", "npxg_p90", NPXG, 71)],
    },
  ],
  excluded: { "over budget": 2, "sideways move": 4 },
};

export const emptyShortlist: Schemas["ShortlistResponse"] = {
  ...shortlist,
  candidates: [],
  excluded: { "over budget": 9 },
};

function kpi(
  id: string,
  label: string,
  weight: number,
  value: number,
  pct: number | null,
  extra: Partial<Schemas["KpiFact"]> = {},
): Schemas["KpiFact"] {
  return {
    kpi: id,
    label,
    weight,
    is_proxy: false,
    proxy_for: null,
    value,
    raw_p90: value,
    percentile: pct,
    band:
      pct === null
        ? null
        : pct >= 90
          ? "elite"
          : pct >= 75
            ? "strong"
            : pct >= 50
              ? "above_average"
              : pct >= 25
                ? "below_average"
                : "weak",
    n_peers: 48,
    source: "understat",
    as_of: AS_OF,
    padj_status: null,
    ...extra,
  };
}

export const factSheet: Schemas["FactSheet"] = {
  player_id: 11,
  player_name: "Sam Synthetic",
  team_id: 2,
  team_name: "Fixture Town",
  position_group: "ST",
  birth_date: "1999-04-02",
  age: 27.5,
  as_of: "2026-10-01",
  season_mode: "blended",
  current_season: "2026-27",
  previous_season: "2025-26",
  minutes: 540,
  effective_minutes: 1540,
  fpl_status: "a",
  chance_of_playing: null,
  status_as_of: AS_OF,
  contract_expiry: "2028-06-30",
  market_value: {
    value_eur: 38_000_000,
    tm_last_updated: "2026-09-15",
    source: "transfermarkt",
    is_stale: false,
  },
  kpis: [
    kpi("npxg_p90", NPXG, 0.4, 0.52, 93),
    kpi("shots_p90", SHOTS, 0.2, 3.4, 81),
    kpi("xg_chain_p90", CHAIN, 0.15, 0.61, null, {
      is_proxy: true,
      proxy_for: "ball progression (progressive passes need event data)",
    }),
    kpi(
      "goals_minus_xg_p90",
      "Goals minus xG (per 90; shown, not weighted: finishing is noisy)",
      0,
      0.08,
      70,
    ),
  ],
  strengths: ["npxg_p90", "shots_p90"],
  concerns: [],
  role: { label: "high Non-penalty xG, high Shots", trained_at: AS_OF, git_sha: "abc1234" },
  comparables: [],
  implied_value: shortlist.candidates[0]?.implied_value ?? null,
  fit: null,
  caveats: [
    {
      kind: "proxy_metric",
      text: "Proxy metrics (stand-ins for data not freely available): Possession involvement (xGChain per 90).",
    },
  ],
  sources: [
    { source: "fpl", as_of: AS_OF },
    { source: "transfermarkt", as_of: "2026-09-15" },
    { source: "understat", as_of: AS_OF },
  ],
};

export const incumbentSheet: Schemas["FactSheet"] = {
  ...factSheet,
  player_id: 7,
  player_name: "Ivo Placeholder",
  team_id: 1,
  team_name: "Synthetic Rovers",
  market_value: null,
  implied_value: null,
  role: null,
};

export const similar: Schemas["SimilarResponse"] = {
  player_id: 11,
  player_name: "Sam Synthetic",
  position_group: "ST",
  season_mode: "blended",
  results: [
    {
      player_id: 21,
      player_name: "Kit Example",
      team_id: 3,
      team_name: "Mock City",
      similarity: 0.91,
    },
    { player_id: 22, player_name: "Lou Sample", team_id: null, team_name: null, similarity: 0.84 },
  ],
};

export const report: Schemas["ReportResponse"] = {
  report: {
    text: "SCOUTING REPORT: Sam Synthetic\nFixture Town · ST · age 27.5\n\nVERDICT\nRecommended.\n",
    engine: "template",
    requested_engine: "template",
    fallback_reason: null,
    violations: [],
  },
  facts: factSheet,
};

export const playerSearch: Schemas["PlayerSearchHit"][] = [
  {
    player_id: 11,
    name: "Sam Synthetic",
    team_id: 2,
    team_name: "Fixture Town",
    position_group: "ST",
    matched: "Sam Synthetic",
    kind: "prefix",
    score: 90,
  },
  {
    player_id: 7,
    name: "Ivo Placeholder",
    team_id: 1,
    team_name: "Synthetic Rovers",
    position_group: "ST",
    matched: "Ivo Placeholder",
    kind: "prefix",
    score: 90,
  },
];

export const compare: Schemas["CompareResponse"] = {
  season_mode: "blended",
  a: {
    player_id: 11,
    player_name: "Sam Synthetic",
    team_id: 2,
    team_name: "Fixture Town",
    position_group: "ST",
    age: 27.5,
    minutes: 540,
    effective_minutes: 1540,
    market_value: factSheet.market_value,
  },
  b: {
    player_id: 7,
    player_name: "Ivo Placeholder",
    team_id: 1,
    team_name: "Synthetic Rovers",
    position_group: "ST",
    age: 29.1,
    minutes: 610,
    effective_minutes: 2100,
    market_value: null,
  },
  team: { team_id: 1, name: "Synthetic Rovers" },
  rows: [
    {
      kpi: "npxg_p90",
      label: NPXG,
      is_proxy: false,
      is_need: true,
      a: kpi("npxg_p90", NPXG, 0.4, 0.52, 93),
      b: kpi("npxg_p90", NPXG, 0.4, 0.21, 35),
      delta: 58,
    },
    {
      kpi: "xg_chain_p90",
      label: CHAIN,
      is_proxy: true,
      is_need: false,
      a: null,
      b: kpi("xg_chain_p90", CHAIN, 0.15, 0.4, 44),
      delta: null,
    },
  ],
};

export const freshness: Schemas["FreshnessResponse"] = {
  warehouse_version: "2026-10-01T06:00:00+00:00",
  validation_summary: "validation: 12 tables ok",
  sources: [
    { source: "fpl", last_fetched: "2026-10-01T05:00:00Z", age_hours: 5, stale: false },
    { source: "transfermarkt", last_fetched: "2026-09-15T05:00:00Z", age_hours: 389, stale: true },
  ],
  coverage: { understat: 0.991, transfermarkt: 0.962 },
  review_count: 3,
  fpl_schema: "ok",
  warnings: ["transfermarkt is stale (389 h old)"],
};

export const methodology: Schemas["MethodologyResponse"] = {
  kpis: [
    {
      kpi: "npxg_p90",
      label: NPXG,
      source: "understat",
      higher_is_better: true,
      is_proxy: false,
      proxy_for: null,
      possession_adjusted: false,
    },
    {
      kpi: "def_activity_padj_p90",
      label: "Defensive activity, possession-adjusted (per 90)",
      source: "fpl",
      higher_is_better: true,
      is_proxy: true,
      proxy_for: "player-level pressing",
      possession_adjusted: true,
    },
  ],
  position_groups: { ST: { npxg_p90: 1 }, CB: { def_activity_padj_p90: 1 } },
  team_kpis: [
    {
      kpi: "xg_p90",
      label: "xG for (per 90)",
      source: "understat",
      higher_is_better: true,
      responsible_groups: ["ST"],
    },
  ],
  fit_weights: {
    need_fill: 0.4,
    role_quality: 0.25,
    reliability: 0.15,
    style_fit: 0.1,
    age_profile: 0.1,
  },
  upgrade_gate_min_delta: 15,
  peak_age: { ST: [24, 29] },
  parameters: { blend_lambda: 0.5, percentile_min_minutes: 600, default_benchmark: "top6" },
  percentile_bands: { elite: 90, strong: 75, above_average: 50, below_average: 25 },
  value_model_caveat: "Stats-implied value, not a fee prediction.",
  models: [
    { name: "role archetypes", trained_at: AS_OF, git_sha: "abc1234", rows: 412 },
    { name: "value model", trained_at: null, git_sha: null, rows: 0 },
  ],
  limitations: ["Player-level pressing is a proxy."],
};
