import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { report } from "../test/data.synthetic";
import { apiPath, errorBody } from "../test/handlers.synthetic";
import { present, renderWithProviders } from "../test/render";
import { server } from "../test/server";
import { PlayerPage } from "./PlayerPage";

const PATH = "/players/:playerId";

describe("PlayerPage", () => {
  it("shows header facts with receipts, percentile bars and value", async () => {
    renderWithProviders(<PlayerPage />, { route: "/players/11", path: PATH });
    expect(await screen.findByRole("heading", { name: "Sam Synthetic" })).toBeInTheDocument();
    expect(screen.getByText("Striker (ST)")).toBeInTheDocument();
    expect(screen.getByText(/€38.0m · TM as of 15 Sept? 2026 · Transfermarkt/)).toBeInTheDocument();
    expect(screen.getByText("high Non-penalty xG, high Shots")).toBeInTheDocument();
    const npxg = screen.getByRole("meter", { name: "Non-penalty xG (per 90)" });
    expect(npxg).toHaveAttribute("aria-valuetext", "93rd percentile");
    // A KPI without a percentile reads "Not available", not 0.
    const chain = screen.getByRole("meter", { name: "Possession involvement (xGChain per 90)" });
    expect(chain).toHaveAttribute("aria-valuetext", "Not available");
    expect(chain).not.toHaveAttribute("aria-valuenow");
    expect(screen.getAllByText("proxy").length).toBeGreaterThan(0);
    expect(screen.getByText(/0.52 · 48 peers/)).toBeInTheDocument();
    expect(screen.getByText(/0.08 · 48 peers · not weighted/)).toBeInTheDocument();
    expect(screen.getByText("Undervalued")).toBeInTheDocument();
    expect(screen.getByText(/Proxy metrics \(stand-ins/)).toBeInTheDocument();
  });

  it("shows similar players and the scouting report with a copy button", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PlayerPage />, { route: "/players/11?team=1", path: PATH });
    expect(await screen.findByRole("link", { name: "Kit Example" })).toHaveAttribute(
      "href",
      "/players/21",
    );
    expect(screen.getByText(/Not available · cosine 0.84/)).toBeInTheDocument();
    const text = await screen.findByText(/SCOUTING REPORT: Sam Synthetic/);
    expect(text.tagName).toBe("PRE");
    expect(screen.getByText(/every number comes from the fact sheet/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy report" }));
    expect(await navigator.clipboard.readText()).toBe(report.report.text);
    expect(screen.getByText("Copied.")).toBeInTheDocument();
    expect(await screen.findByText(/Fit against: Synthetic Rovers/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear club" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/players/11");
    expect(screen.getByTestId("location")).not.toHaveTextContent("team=");
  });

  it("asks the report for the selected club", async () => {
    const teams: (string | null)[] = [];
    server.use(
      http.get(apiPath("/players/:id/report"), ({ request }) => {
        teams.push(new URL(request.url).searchParams.get("team_id"));
        return HttpResponse.json(report);
      }),
    );
    renderWithProviders(<PlayerPage />, { route: "/players/11?team=3", path: PATH });
    await screen.findByText(/SCOUTING REPORT/);
    expect(teams).toEqual(["3"]);
  });

  it("explains a report fallback", async () => {
    server.use(
      http.get(apiPath("/players/:id/report"), () =>
        HttpResponse.json({
          ...report,
          report: {
            ...report.report,
            requested_engine: "ollama",
            fallback_reason: "LLM output failed grounding",
          },
        }),
      ),
    );
    renderWithProviders(<PlayerPage />, { route: "/players/11", path: PATH });
    expect(await screen.findByText(/LLM output failed grounding/)).toBeInTheDocument();
  });

  it("shows when similar players are not available", async () => {
    server.use(
      http.get(apiPath("/players/:id/similar"), () =>
        HttpResponse.json(errorBody("not_found", "no complete profile"), { status: 404 }),
      ),
    );
    renderWithProviders(<PlayerPage />, { route: "/players/11", path: PATH });
    const card = (await screen.findByRole("heading", { name: "Similar players" })).closest(
      "section",
    );
    expect(
      await within(present(card)).findByText(/Not available: the player is not ranked/),
    ).toBeInTheDocument();
  });

  it("shows a loading state", async () => {
    server.use(
      http.get(apiPath("/players/:id"), async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    renderWithProviders(<PlayerPage />, { route: "/players/11", path: PATH });
    expect(await screen.findByRole("status")).toHaveTextContent("Loading the player…");
  });

  it("shows unknown players as not available", async () => {
    server.use(
      http.get(apiPath("/players/:id"), () =>
        HttpResponse.json(errorBody("not_found", "player 99 has no current-season minutes"), {
          status: 404,
        }),
      ),
    );
    renderWithProviders(<PlayerPage />, { route: "/players/99", path: PATH });
    expect(await screen.findByText("player 99 has no current-season minutes")).toBeInTheDocument();
  });

  it("shows errors", async () => {
    server.use(
      http.get(apiPath("/players/:id"), () =>
        HttpResponse.json(errorBody("x", "boom"), { status: 500 }),
      ),
    );
    renderWithProviders(<PlayerPage />, { route: "/players/11", path: PATH });
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });

  it("navigates to the compare page", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PlayerPage />, { route: "/players/11?team=1", path: PATH });
    await screen.findByRole("heading", { name: "Sam Synthetic" });
    await user.type(screen.getByRole("combobox", { name: "Compare with" }), "Ivo");
    await user.click(await screen.findByRole("option", { name: /Ivo Placeholder/ }));
    expect(screen.getByTestId("location")).toHaveTextContent("/compare?a=11&b=7&team=1");
  });
});
