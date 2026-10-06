import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { diagnosisNoShortfall } from "../test/data.synthetic";
import { apiPath, errorBody } from "../test/handlers.synthetic";
import { present, renderWithProviders } from "../test/render";
import { server } from "../test/server";
import { DiagnosisPage } from "./DiagnosisPage";

describe("DiagnosisPage", () => {
  it("starts with an empty state and a club search", () => {
    renderWithProviders(<DiagnosisPage />);
    expect(screen.getByRole("heading", { name: "Club diagnosis" })).toBeInTheDocument();
    expect(screen.getByText("Pick a club to start")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Pick a club" })).toBeInTheDocument();
  });

  it("finds a club by alias with the keyboard and loads its diagnosis", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DiagnosisPage />);
    const box = screen.getByRole("combobox", { name: "Pick a club" });
    await user.type(box, "rov");
    const option = await screen.findByRole("option", { name: /Synthetic Rovers/ });
    expect(option).toHaveTextContent("matched “Rovers”");
    await user.keyboard("{ArrowDown}{Enter}");
    expect(screen.getByTestId("location")).toHaveTextContent("/?team=1");
    expect(await screen.findByText(/Diagnosing the squad|compared with/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /#1 Striker \(ST\)/ })).toBeInTheDocument();
  });

  it("shows typo suggestions and a no-match message", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DiagnosisPage />);
    const box = screen.getByRole("combobox", { name: "Pick a club" });
    await user.type(box, "mok cty");
    expect(
      await screen.findByText("No exact match. Did you mean one of these?"),
    ).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Mock City/ })).toBeInTheDocument();
    await user.clear(box);
    await user.type(box, "zzz");
    expect(await screen.findByText("No club matches. Check the spelling.")).toBeInTheDocument();
  });

  it("renders needs, heat strip, weak links, risks and team needs with receipts", async () => {
    renderWithProviders(<DiagnosisPage />, { route: "/?team=1" });
    const need = await screen.findByRole("heading", { name: /#1 Striker \(ST\) · severity 18\.4/ });
    const card = need.closest("section");
    expect(card).not.toBeNull();
    const scoped = within(present(card));
    expect(scoped.getAllByText("proxy").length).toBeGreaterThan(0);
    expect(scoped.getByText("+31")).toBeInTheDocument();
    expect(scoped.getByText(/Understat · as of 28 Sept? 2026/)).toBeInTheDocument();
    expect(
      screen.getByText(/compared with Top 6 of last season \(Fixture Town, Mock City\)/),
    ).toBeInTheDocument();
    const strip = screen.getByRole("list", { name: "Need severity by position group" });
    expect(within(strip).getAllByRole("link")).toHaveLength(4);
    expect(within(strip).getAllByRole("link")[0]).toHaveAttribute("href", "/clubs/1/needs/1-ST");
    expect(screen.getAllByText(/Ivo Placeholder/).length).toBeGreaterThan(0);
    expect(screen.getByText("Depth")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "xG for (per 90)" })).toBeInTheDocument();
    // Goalkeeper ratings always carry their limited-metrics caveat.
    expect(screen.getByText(/Goalkeeper ratings are limited/)).toBeInTheDocument();
    // Only groups with a shortfall become top needs (the W group has severity 0).
    expect(screen.queryByRole("heading", { name: /Winger \(W\)/ })).not.toBeInTheDocument();
  });

  it("links a need to its shortlist and keeps the analysis settings", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DiagnosisPage />, { route: "/?team=1&mode=current" });
    const buttons = await screen.findAllByRole("button", { name: "Find players for this need" });
    await user.click(present(buttons[0]));
    expect(screen.getByTestId("location")).toHaveTextContent("/clubs/1/needs/1-ST?mode=current");
  });

  it("puts season mode and benchmark in the URL", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DiagnosisPage />, { route: "/?team=1" });
    await screen.findByRole("heading", { name: /#1 Striker/ });
    await user.click(screen.getByRole("radio", { name: "This season only" }));
    expect(screen.getByTestId("location")).toHaveTextContent("mode=current");
    await user.selectOptions(screen.getByRole("combobox", { name: "Benchmark" }), "league");
    expect(screen.getByTestId("location")).toHaveTextContent("benchmark=league");
  });

  it("asks for custom benchmark clubs before diagnosing", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DiagnosisPage />, { route: "/?team=1&benchmark=custom" });
    expect(screen.getByText("Choose the custom benchmark clubs")).toBeInTheDocument();
    await user.click(await screen.findByRole("checkbox", { name: "Mock City" }));
    expect(screen.getByTestId("location")).toHaveTextContent("custom=3");
    expect(screen.queryByRole("checkbox", { name: "Synthetic Rovers" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /#1 Striker/ })).toBeInTheDocument();
  });

  it("shows a loading state", async () => {
    server.use(
      http.get(apiPath("/teams/:id/diagnosis"), async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    renderWithProviders(<DiagnosisPage />, { route: "/?team=1" });
    expect(await screen.findByRole("status")).toHaveTextContent("Diagnosing the squad…");
  });

  it("shows the empty state when nothing trails the benchmark", async () => {
    server.use(
      http.get(apiPath("/teams/:id/diagnosis"), () => HttpResponse.json(diagnosisNoShortfall)),
    );
    renderWithProviders(<DiagnosisPage />, { route: "/?team=1" });
    expect(await screen.findByText("No shortfalls against this benchmark")).toBeInTheDocument();
    expect(screen.getByText(/No regular starter rates below/)).toBeInTheDocument();
    expect(screen.getByText(/No depth, age or contract risk/)).toBeInTheDocument();
  });

  it("tells the user to build the warehouse when there is no data", async () => {
    server.use(
      http.get(apiPath("/teams/:id/diagnosis"), () =>
        HttpResponse.json(errorBody("warehouse_not_ready", "Run scout build"), { status: 503 }),
      ),
    );
    renderWithProviders(<DiagnosisPage />, { route: "/?team=1" });
    expect(await screen.findByText("No data yet")).toBeInTheDocument();
  });

  it("shows API errors with a retry", async () => {
    let calls = 0;
    server.use(
      http.get(apiPath("/teams/:id/diagnosis"), () => {
        calls += 1;
        return HttpResponse.json(errorBody("scout_error", "Diagnosis exploded"), { status: 500 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DiagnosisPage />, { route: "/?team=1" });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Diagnosis exploded");
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(calls).toBe(2);
  });
});
