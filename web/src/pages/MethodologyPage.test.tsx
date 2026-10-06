import { screen } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { freshness } from "../test/data.synthetic";
import { apiPath, errorBody } from "../test/handlers.synthetic";
import { renderWithProviders } from "../test/render";
import { server } from "../test/server";
import { MethodologyPage } from "./MethodologyPage";

describe("MethodologyPage", () => {
  it("lists freshness, definitions, weights, proxies, models and limitations", async () => {
    renderWithProviders(<MethodologyPage />);
    expect(await screen.findByText("FPL")).toBeInTheDocument();
    expect(screen.getByText("stale")).toBeInTheDocument();
    expect(screen.getByText(/Understat 99% · Transfermarkt 96%/)).toBeInTheDocument();
    expect(screen.getByText("transfermarkt is stale (389 h old)")).toBeInTheDocument();
    expect(await screen.findByText(/Stands in for player-level pressing/)).toBeInTheDocument();
    expect(screen.getByText(/at least 15 percentile points/)).toBeInTheDocument();
    expect(screen.getByText(/not trained yet/)).toBeInTheDocument();
    expect(screen.getByText(/412 players/)).toBeInTheDocument();
    expect(screen.getByText("Player-level pressing is a proxy.")).toBeInTheDocument();
    expect(screen.getByText(/Peak-age windows: ST 24–29/)).toBeInTheDocument();
  });

  it("shows empty freshness before the first ingest", async () => {
    server.use(
      http.get(apiPath("/meta/freshness"), () =>
        HttpResponse.json({ ...freshness, sources: [], coverage: {}, warnings: [] }),
      ),
    );
    renderWithProviders(<MethodologyPage />);
    expect(await screen.findByText(/No snapshots yet/)).toBeInTheDocument();
    expect(screen.getByText(/share of FPL minutes\): Not available/)).toBeInTheDocument();
  });

  it("shows loading states", async () => {
    server.use(
      http.get(apiPath("/meta/freshness"), async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
      http.get(apiPath("/meta/methodology"), async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    renderWithProviders(<MethodologyPage />);
    expect(await screen.findByText("Checking data freshness…")).toBeInTheDocument();
    expect(screen.getByText("Loading definitions…")).toBeInTheDocument();
  });

  it("shows the no-data state and errors", async () => {
    server.use(
      http.get(apiPath("/meta/freshness"), () =>
        HttpResponse.json(errorBody("x", "freshness failed"), { status: 500 }),
      ),
      http.get(apiPath("/meta/methodology"), () =>
        HttpResponse.json(errorBody("warehouse_not_ready", "build first"), { status: 503 }),
      ),
    );
    renderWithProviders(<MethodologyPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("freshness failed");
    expect(await screen.findByText("No data yet")).toBeInTheDocument();
  });
});
