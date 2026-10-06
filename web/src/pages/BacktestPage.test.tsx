import { screen } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { backtest } from "../test/data.synthetic";
import { apiPath, errorBody } from "../test/handlers.synthetic";
import { renderWithProviders } from "../test/render";
import { server } from "../test/server";
import { BacktestPage } from "./BacktestPage";

describe("BacktestPage", () => {
  it("shows precision against the baselines with per-club receipts", async () => {
    renderWithProviders(<BacktestPage />);
    expect(await screen.findByText("Engine precision@3")).toBeInTheDocument();
    // Summary metric plus the club row (precision 50%, baseline 25%).
    expect(screen.getAllByText("50%")).toHaveLength(2);
    expect(screen.getAllByText("25%")).toHaveLength(2);
    expect(screen.getByText("signed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Nia Newcomer" })).toHaveAttribute(
      "href",
      "/players/31",
    );
    expect(screen.getByText("no shortfall")).toBeInTheDocument();
    expect(screen.getByText("none yet")).toBeInTheDocument();
    expect(screen.getByText(/Not evaluated: promoted \(no diagnosis\) 3/)).toBeInTheDocument();
    expect(screen.getByText(/as of 28 Sept? 2026/)).toBeInTheDocument();
    expect(screen.getByText(/Exploratory/)).toBeInTheDocument();
    expect(screen.getByText(/the top 6 of the 2025-26 table/)).toBeInTheDocument();
    expect(screen.getByText(/averaged over 1 club\./)).toBeInTheDocument();
  });

  it("explains an empty backtest early in the season", async () => {
    server.use(
      http.get(apiPath("/meta/backtest"), () =>
        HttpResponse.json({
          ...backtest,
          evaluated: 0,
          precision: null,
          clubs: [],
          hit_rate: null,
        }),
      ),
    );
    renderWithProviders(<BacktestPage />);
    expect(await screen.findByText("Nothing to evaluate yet")).toBeInTheDocument();
    expect(screen.getAllByText("Not available").length).toBeGreaterThan(0);
  });

  it("shows loading and error states", async () => {
    server.use(
      http.get(apiPath("/meta/backtest"), async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    const { unmount } = renderWithProviders(<BacktestPage />);
    expect(await screen.findByText("Re-running last season's diagnosis…")).toBeInTheDocument();
    unmount();
    server.use(
      http.get(apiPath("/meta/backtest"), () =>
        HttpResponse.json(errorBody("not_found", "no FPL history for 2025-26"), { status: 404 }),
      ),
    );
    renderWithProviders(<BacktestPage />);
    expect(await screen.findByText("no FPL history for 2025-26")).toBeInTheDocument();
  });
});
