import type { ReactNode } from "react";
import { NavLink } from "react-router";

import { useHealth } from "../hooks/useHealth";

const NAV = [
  { to: "/", label: "Club diagnosis", end: true },
  { to: "/compare", label: "Compare", end: false },
  { to: "/backtest", label: "Backtest", end: false },
  { to: "/methodology", label: "Methodology & data", end: false },
] as const;

function ApiStatus() {
  const health = useHealth();
  if (health.isPending) {
    return <span className="text-slate-500">API: checking…</span>;
  }
  if (health.isError) {
    return <span className="text-red-700">API: unreachable</span>;
  }
  const build = health.data.warehouse_version ?? "no warehouse build yet";
  return (
    <span className="text-slate-600">
      API v{health.data.version} · warehouse: {build}
    </span>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:m-2 focus:rounded focus:bg-white focus:p-2"
      >
        Skip to content
      </a>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-6 py-3">
          <NavLink to="/" className="text-lg font-semibold text-accent-800">
            PL Scout Engine
          </NavLink>
          <nav aria-label="Main">
            <ul className="flex gap-4 text-sm">
              {NAV.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      isActive
                        ? "font-semibold text-accent-800 underline underline-offset-4"
                        : "text-slate-700 hover:text-accent-700"
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-6xl px-6 py-6">
        {children}
      </main>
      <footer className="mx-auto max-w-6xl px-6 pb-8 text-xs">
        <ApiStatus />
        <p className="mt-1 text-slate-500">
          No number without a receipt. Personal, non-commercial use; data from free public sources.
        </p>
      </footer>
    </div>
  );
}
