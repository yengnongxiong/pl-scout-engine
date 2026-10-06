import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiPath, errorBody } from "../test/handlers.synthetic";
import { renderWithProviders } from "../test/render";
import { server } from "../test/server";
import { ComparePage } from "./ComparePage";

describe("ComparePage", () => {
  it("asks for two players", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ComparePage />, { route: "/compare" });
    expect(screen.getByText("Pick two players")).toBeInTheDocument();
    await user.type(screen.getByRole("combobox", { name: "Player A (candidate)" }), "Sam");
    await user.click(await screen.findByRole("option", { name: /Sam Synthetic/ }));
    expect(screen.getByTestId("location")).toHaveTextContent("a=11");
  });

  it("refuses to compare a player with themselves", () => {
    renderWithProviders(<ComparePage />, { route: "/compare?a=11&b=11" });
    expect(screen.getByText("Pick two different players")).toBeInTheDocument();
  });

  it("shows percentiles side by side with deltas and need KPIs", async () => {
    renderWithProviders(<ComparePage />, { route: "/compare?a=11&b=7&team=1" });
    expect(await screen.findByText(/Synthetic Rovers need KPIs highlighted/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sam Synthetic" })).toHaveAttribute(
      "href",
      "/players/11",
    );
    expect(screen.getByText("+58")).toBeInTheDocument();
    expect(screen.getByText("(club need)")).toBeInTheDocument();
    const missing = screen.getByRole("meter", {
      name: "Sam Synthetic: Possession involvement (xGChain per 90)",
    });
    expect(missing).toHaveAttribute("aria-valuetext", "Not available");
    expect(screen.getAllByText("Not available").length).toBeGreaterThan(0);
  });

  it("shows a loading state", async () => {
    server.use(
      http.get(apiPath("/compare"), async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    renderWithProviders(<ComparePage />, { route: "/compare?a=11&b=7" });
    expect(await screen.findByRole("status")).toHaveTextContent("Lining up the numbers…");
  });

  it("shows errors", async () => {
    server.use(
      http.get(apiPath("/compare"), () =>
        HttpResponse.json(errorBody("invalid_request", "compare two different players"), {
          status: 422,
        }),
      ),
    );
    renderWithProviders(<ComparePage />, { route: "/compare?a=11&b=7" });
    expect(await screen.findByRole("alert")).toHaveTextContent("compare two different players");
  });
});
