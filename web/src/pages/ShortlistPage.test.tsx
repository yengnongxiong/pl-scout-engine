import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { emptyShortlist } from "../test/data.synthetic";
import { apiPath, errorBody } from "../test/handlers.synthetic";
import { present, renderWithProviders } from "../test/render";
import { server } from "../test/server";
import { ShortlistPage } from "./ShortlistPage";

const PATH = "/clubs/:teamId/needs/:needId";
const ROUTE = "/clubs/1/needs/1-ST";

function rowNames(): string[] {
  const table = screen.getByRole("table", { name: /Shortlist ranked by FitScore/ });
  return within(table)
    .getAllByRole("link")
    .map((a) => a.textContent);
}

describe("ShortlistPage", () => {
  it("lists candidates with values, receipts and gates", async () => {
    renderWithProviders(<ShortlistPage />, { route: ROUTE, path: PATH });
    expect(
      await screen.findByRole("heading", { name: "Shortlist: Synthetic Rovers · Striker" }),
    ).toBeInTheDocument();
    expect(rowNames()).toEqual(["Sam Synthetic", "Alex Example"]);
    expect(screen.getByText("€38.0m")).toBeInTheDocument();
    expect(screen.getByText("stale")).toBeInTheDocument();
    expect(screen.getAllByText("Upgrade")).toHaveLength(2);
    expect(screen.getByText("78.4")).toBeInTheDocument();
    expect(screen.getByText(/Filtered out: over budget 2, sideways move 4/)).toBeInTheDocument();
    expect(screen.getByText(/Transfermarkt · as of 15 Sept? 2026/)).toBeInTheDocument();
    expect(screen.getByText(/Ivo Placeholder/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Sam Synthetic" })[0]).toHaveAttribute(
      "href",
      "/players/11?team=1",
    );
  });

  it("sorts by a column and expands the FitScore breakdown", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ShortlistPage />, { route: ROUTE, path: PATH });
    await screen.findByRole("table", { name: /Shortlist/ });
    // Numeric columns sort descending first, then ascending.
    await user.click(screen.getByRole("button", { name: "Age" }));
    expect(rowNames()).toEqual(["Alex Example", "Sam Synthetic"]);
    expect(screen.getByRole("columnheader", { name: /Age/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    await user.click(screen.getByRole("button", { name: /Age/ }));
    expect(rowNames()).toEqual(["Sam Synthetic", "Alex Example"]);
    await user.click(screen.getByRole("button", { name: /Why\?\s*Sam Synthetic/ }));
    expect(screen.getByText("FitScore 78.4 breakdown")).toBeInTheDocument();
    expect(screen.getByText("NeedFill")).toBeInTheDocument();
    // A missing component (StyleFit) reads "Not available", never 0.
    const style = present(screen.getByText("StyleFit").parentElement);
    expect(style).toHaveTextContent("Not available");
    expect(screen.getByRole("link", { name: "Compare with Ivo Placeholder" })).toHaveAttribute(
      "href",
      "/compare?a=11&b=7&team=1",
    );
    expect(screen.getByRole("meter", { name: /Non-penalty xG/ })).toHaveAttribute(
      "aria-valuenow",
      "93",
    );
    expect(screen.getByText("(club need)")).toBeInTheDocument();
  });

  it("applies filters through the URL and sends them to the API", async () => {
    const seen: URLSearchParams[] = [];
    server.use(
      http.get(apiPath("/teams/:id/recommendations"), ({ request }) => {
        seen.push(new URL(request.url).searchParams);
        return HttpResponse.json(emptyShortlist);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ShortlistPage />, { route: ROUTE, path: PATH });
    await screen.findByText("No candidates");
    await user.type(screen.getByLabelText("Max value (€m)"), "20");
    await user.type(screen.getByLabelText("Max age"), "28");
    await user.click(screen.getByLabelText("Include sideways moves"));
    await user.click(screen.getByText(/Exclude clubs/));
    await user.click(screen.getByRole("checkbox", { name: "Mock City" }));
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    const location = screen.getByTestId("location");
    expect(location).toHaveTextContent("maxValue=20");
    expect(location).toHaveTextContent("maxAge=28");
    expect(location).toHaveTextContent("exclude=3");
    expect(location).toHaveTextContent("sideways=1");
    await screen.findByText("No candidates");
    const last = seen.at(-1);
    expect(last?.get("max_value_eur")).toBe("20000000");
    expect(last?.get("max_age")).toBe("28");
    expect(last?.getAll("exclude_team_ids")).toEqual(["3"]);
    expect(last?.get("include_sideways")).toBe("true");
    expect(last?.get("need_id")).toBe("1-ST");
    expect(screen.getByText(/Filtered out: over budget 9/)).toBeInTheDocument();
  });

  it("shows the Moneyball view", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ShortlistPage />, { route: ROUTE, path: PATH });
    await screen.findByRole("table", { name: /Shortlist/ });
    await user.click(screen.getByLabelText(/Moneyball view/));
    expect(screen.getByTestId("location")).toHaveTextContent("moneyball=1");
    expect(screen.getByRole("heading", { name: "Moneyball view" })).toBeInTheDocument();
    expect(screen.getAllByText("Undervalued").length).toBeGreaterThan(0);
    expect(screen.getByText(/€52.4m/)).toBeInTheDocument();
    await user.click(screen.getByLabelText(/Only players the stats rate above/));
    expect(rowNames()).toEqual(["Sam Synthetic"]);
  });

  it("shows a loading state", async () => {
    server.use(
      http.get(apiPath("/teams/:id/recommendations"), async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    renderWithProviders(<ShortlistPage />, { route: ROUTE, path: PATH });
    expect(await screen.findByRole("status")).toHaveTextContent("Scoring candidates…");
  });

  it("shows unknown needs as not available", async () => {
    server.use(
      http.get(apiPath("/teams/:id/recommendations"), () =>
        HttpResponse.json(errorBody("not_found", "no XX need for club 1"), { status: 404 }),
      ),
    );
    renderWithProviders(<ShortlistPage />, { route: "/clubs/1/needs/1-XX", path: PATH });
    expect(await screen.findByText("no XX need for club 1")).toBeInTheDocument();
  });

  it("shows server errors", async () => {
    server.use(http.get(apiPath("/teams/:id/recommendations"), () => HttpResponse.error()));
    renderWithProviders(<ShortlistPage />, { route: ROUTE, path: PATH });
    expect(await screen.findByRole("alert")).toHaveTextContent("The API could not be reached");
  });
});
