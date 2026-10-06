import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { App } from "./App";
import { apiPath } from "./test/handlers.synthetic";
import { renderWithProviders } from "./test/render";
import { server } from "./test/server";

describe("App shell", () => {
  it("renders navigation and the API status", async () => {
    renderWithProviders(<App />);
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByText("API: checking…")).toBeInTheDocument();
    expect(await screen.findByText(/warehouse: synthetic-build/)).toBeInTheDocument();
  });

  it("shows when the API is unreachable", async () => {
    server.use(http.get(apiPath("/health"), () => HttpResponse.error()));
    renderWithProviders(<App />);
    expect(await screen.findByText("API: unreachable")).toBeInTheDocument();
  });

  it("routes to the methodology page", () => {
    renderWithProviders(<App />, { route: "/methodology" });
    expect(screen.getByRole("heading", { name: "Methodology & data" })).toBeInTheDocument();
  });
});
