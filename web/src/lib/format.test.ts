import { describe, expect, it } from "vitest";

import {
  NOT_AVAILABLE,
  formatAge,
  formatDate,
  formatEurMillions,
  formatGap,
  formatInteger,
  formatMinutes,
  formatNumber,
  formatPer90,
  formatPercentile,
  formatReceipt,
  formatScore,
  formatShare,
  formatDateTime,
} from "./format";

describe("format", () => {
  it("renders missing values as Not available, never 0", () => {
    for (const fn of [
      formatPer90,
      formatInteger,
      formatMinutes,
      formatPercentile,
      formatScore,
      formatGap,
      formatEurMillions,
      formatAge,
      formatShare,
    ]) {
      expect(fn(null)).toBe(NOT_AVAILABLE);
      expect(fn(undefined)).toBe(NOT_AVAILABLE);
      expect(fn(Number.NaN)).toBe(NOT_AVAILABLE);
    }
    expect(formatDate(null)).toBe(NOT_AVAILABLE);
    expect(formatDate("not a date")).toBe(NOT_AVAILABLE);
    expect(formatDateTime(undefined)).toBe(NOT_AVAILABLE);
    expect(formatNumber(null)).toBe(NOT_AVAILABLE);
  });

  it("rounds per PRD §13", () => {
    expect(formatPer90(2.449)).toBe("2.4");
    expect(formatPer90(0)).toBe("0.0");
    expect(formatEurMillions(45_000_000)).toBe("€45.0m");
    expect(formatEurMillions(2_550_000)).toBe("€2.6m");
    expect(formatNumber(1.23456, 2)).toBe("1.23");
  });

  it("formats counts, percentiles, gaps and shares", () => {
    expect(formatInteger(1234.4)).toBe("1,234");
    expect(formatMinutes(1890)).toBe("1,890 min");
    expect(formatPercentile(71.6)).toBe("p72");
    expect(formatGap(12.4)).toBe("+12");
    expect(formatGap(-3)).toBe("−3");
    expect(formatGap(0.2)).toBe("±0");
    expect(formatShare(0.432)).toBe("43%");
    expect(formatScore(78.25)).toBe("78.3");
    expect(formatAge(24.56)).toBe("24.6");
  });

  it("formats calendar dates in UTC without shifting a day", () => {
    expect(formatDate("2026-09-30")).toMatch(/30 Sept? 2026/);
    expect(formatDateTime("2026-09-30T14:05:00Z")).toMatch(/30 Sept? 2026.*14:05.*UTC/);
  });

  it("builds a source receipt", () => {
    expect(formatReceipt("fpl", "2026-09-30")).toMatch(/^fpl · as of 30 Sept? 2026$/);
    expect(formatReceipt(null, null)).toBe(`${NOT_AVAILABLE} · as of ${NOT_AVAILABLE}`);
  });
});
