/**
 * Every number, currency and date shown in the UI is formatted here (CLAUDE.md code style).
 *
 * Missing values render as "Not available", never as 0 (data integrity rule 2). Rounding follows
 * PRD §13: one decimal for per-90 rates, EUR millions for Transfermarkt estimated market values.
 */

export const NOT_AVAILABLE = "Not available";

const EUR_PER_MILLION = 1_000_000;

const oneDecimal = new Intl.NumberFormat("en-GB", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const integer = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });
const dateFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
  timeZoneName: "short",
});

type Maybe<T> = T | null | undefined;

function isMissing(value: Maybe<number>): value is null | undefined {
  return value === null || value === undefined || Number.isNaN(value);
}

const twoDecimals = new Intl.NumberFormat("en-GB", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * A per-90 rate: one decimal ("2.4"), two below 1 ("0.52") so xG-type rates stay readable.
 * Same rule as the scouting reports (docs/PROGRESS.md decisions, 2026-10-06).
 */
export function formatPer90(value: Maybe<number>): string {
  if (isMissing(value)) {
    return NOT_AVAILABLE;
  }
  return Math.abs(value) < 1 ? twoDecimals.format(value) : oneDecimal.format(value);
}

/** A percentile as an ordinal ("72nd"). */
export function formatOrdinal(value: Maybe<number>): string {
  if (isMissing(value)) {
    return NOT_AVAILABLE;
  }
  const n = Math.round(value);
  const mod100 = n % 100;
  const suffix =
    mod100 >= 11 && mod100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th");
  return `${integer.format(n)}${suffix}`;
}

/** Peer count with the right noun ("1 peer", "48 peers"). */
export function formatPeers(value: Maybe<number>): string {
  if (isMissing(value)) {
    return NOT_AVAILABLE;
  }
  const n = Math.round(value);
  return `${integer.format(n)} ${n === 1 ? "peer" : "peers"}`;
}

/** A cosine similarity, two decimals. */
export function formatSimilarity(value: Maybe<number>): string {
  return isMissing(value) ? NOT_AVAILABLE : twoDecimals.format(value);
}

/** A generic number with a fixed number of decimals. */
export function formatNumber(value: Maybe<number>, decimals = 1): string {
  if (isMissing(value)) {
    return NOT_AVAILABLE;
  }
  return new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/** Whole numbers with thousands separators ("1,234"). */
export function formatInteger(value: Maybe<number>): string {
  return isMissing(value) ? NOT_AVAILABLE : integer.format(Math.round(value));
}

/** Minutes played ("1,234 min"). */
export function formatMinutes(value: Maybe<number>): string {
  return isMissing(value) ? NOT_AVAILABLE : `${integer.format(Math.round(value))} min`;
}

/** A percentile on the 0-100 scale, ordinal-free ("p72"). */
export function formatPercentile(value: Maybe<number>): string {
  return isMissing(value) ? NOT_AVAILABLE : `p${integer.format(Math.round(value))}`;
}

/** A 0-100 score (FitScore and its components), one decimal. */
export function formatScore(value: Maybe<number>): string {
  return isMissing(value) ? NOT_AVAILABLE : oneDecimal.format(value);
}

/** A signed gap in percentile points ("+12", "-3"). */
export function formatGap(value: Maybe<number>): string {
  if (isMissing(value)) {
    return NOT_AVAILABLE;
  }
  const rounded = Math.round(value);
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "±";
  return `${sign}${integer.format(Math.abs(rounded))}`;
}

/** A Transfermarkt estimated market value in EUR millions ("€45.0m"). */
export function formatEurMillions(valueEur: Maybe<number>): string {
  return isMissing(valueEur) ? NOT_AVAILABLE : `€${oneDecimal.format(valueEur / EUR_PER_MILLION)}m`;
}

/** An age in years, one decimal. */
export function formatAge(value: Maybe<number>): string {
  return isMissing(value) ? NOT_AVAILABLE : oneDecimal.format(value);
}

/** A share in [0, 1] as a whole percentage ("43%"). */
export function formatShare(value: Maybe<number>): string {
  return isMissing(value) ? NOT_AVAILABLE : `${integer.format(Math.round(value * 100))}%`;
}

function parseDate(value: string): Date | null {
  // Plain dates ("2026-09-30") are calendar dates; parse them as UTC so they never shift a day.
  const iso = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00Z` : value;
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** A calendar date ("30 Sept 2026"). */
export function formatDate(value: Maybe<string>): string {
  if (value === null || value === undefined || value === "") {
    return NOT_AVAILABLE;
  }
  const parsed = parseDate(value);
  return parsed === null ? NOT_AVAILABLE : dateFormat.format(parsed);
}

/** A timestamp in UTC ("30 Sept 2026, 14:05 UTC"). */
export function formatDateTime(value: Maybe<string>): string {
  if (value === null || value === undefined || value === "") {
    return NOT_AVAILABLE;
  }
  const parsed = parseDate(value);
  return parsed === null ? NOT_AVAILABLE : dateTimeFormat.format(parsed);
}

/** "Source · as of date" footer text (PRD §13). */
export function formatReceipt(source: Maybe<string>, asOf: Maybe<string>): string {
  const src = source === null || source === undefined || source === "" ? NOT_AVAILABLE : source;
  return `${src} · as of ${formatDate(asOf)}`;
}
