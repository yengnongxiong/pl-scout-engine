/**
 * Capture README screenshots of the dashboard with Playwright.
 *
 *   npm run screenshots              # synthetic test data (no API needed), the default
 *   npm run screenshots -- --live    # your real dashboard: run `uv run scout demo` first
 *
 * Synthetic mode serves the front end's synthetic test data (src/test/data.synthetic.ts:
 * made-up players and clubs) to the production build, so the README never shows numbers
 * without a receipt. Live mode photographs whatever the running app shows.
 * Needs a Chromium for Playwright: `npx playwright install chromium`, or set
 * PLAYWRIGHT_CHROMIUM_PATH to an existing binary.
 */
import { spawn } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "../../docs/screenshots");
const live = process.argv.includes("--live");
const base =
  process.env.SCOUT_WEB_URL ?? (live ? "http://localhost:5173" : "http://localhost:4173");

async function synthetic(page) {
  const data = await import("../src/test/data.synthetic.ts");
  // The golden template report from the Python tests describes the same made-up player.
  const golden = await readFile(
    resolve(here, "../../tests/fixtures/reports/synthetic_report_fit.txt"),
    "utf8",
  );
  const report = { ...data.report, report: { ...data.report.report, text: golden } };
  const routes = [
    [
      /\/api\/health$/,
      { status: "ok", version: "0.1.0", warehouse_version: "synthetic test data" },
    ],
    [/\/api\/teams$/, data.teams],
    [/\/api\/teams\/search/, (url) => data.teamSearch(url.searchParams.get("q") ?? "")],
    [/\/api\/teams\/\d+\/diagnosis/, data.diagnosis],
    [/\/api\/teams\/\d+\/recommendations/, data.shortlist],
    [/\/api\/players\/search/, data.playerSearch],
    [/\/api\/players\/\d+\/similar/, data.similar],
    [/\/api\/players\/\d+\/report/, report],
    [/\/api\/players\/7$/, data.incumbentSheet],
    [/\/api\/players\/\d+$/, data.factSheet],
    [/\/api\/compare/, data.compare],
    [/\/api\/meta\/freshness/, data.freshness],
    [/\/api\/meta\/methodology/, data.methodology],
    [/\/api\/meta\/backtest/, data.backtest],
  ];
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const match = routes.find(([pattern]) => pattern.test(url.pathname));
    if (!match) {
      return route.fulfill({
        status: 404,
        json: { error: { code: "not_found", message: "synthetic", details: {} } },
      });
    }
    const body = typeof match[1] === "function" ? match[1](url) : match[1];
    return route.fulfill({ json: body });
  });
}

async function shoot(page, path, name, waitFor, before) {
  await page.goto(base + path);
  await page.getByText(waitFor).first().waitFor({ timeout: 15000 });
  if (before) await before(page);
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
  console.log(`wrote docs/screenshots/${name}.png`);
}

let server;
if (!live && !process.env.SCOUT_WEB_URL) {
  server = spawn("npx", ["vite", "preview", "--port", "4173", "--strictPort"], {
    cwd: resolve(here, ".."),
    stdio: "ignore",
  });
  await new Promise((r) => setTimeout(r, 2500));
}
await mkdir(out, { recursive: true });
const browser = await chromium.launch(
  process.env.PLAYWRIGHT_CHROMIUM_PATH
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
    : {},
);
try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 860 },
    deviceScaleFactor: 1,
  });
  if (!live) await synthetic(page);
  let team = 1;
  let need = "1-ST";
  let player = 11;
  let incumbent = 7;
  if (live) {
    const teams = await (await fetch(`${base}/api/teams`)).json();
    team = teams[0].team_id;
    const diagnosis = await (await fetch(`${base}/api/teams/${team}/diagnosis`)).json();
    need = diagnosis.needs[0].need_id;
    const shortlist = await (
      await fetch(`${base}/api/teams/${team}/recommendations?need_id=${need}`)
    ).json();
    player = shortlist.candidates[0]?.player_id ?? diagnosis.needs[0].evidence[0].player_id;
    incumbent = shortlist.incumbent?.player_id ?? player;
  }
  await shoot(page, `/?team=${team}`, "diagnosis", "Top needs");
  await shoot(page, `/clubs/${team}/needs/${need}`, "shortlist", "Candidates (", (p) =>
    p.getByRole("button", { name: /Why\?/ }).first().click(),
  );
  await shoot(page, `/clubs/${team}/needs/${need}?moneyball=1`, "moneyball", /Above the diagonal/);
  await shoot(page, `/players/${player}?team=${team}`, "player", /SCOUTING REPORT:/);
  await shoot(
    page,
    `/compare?a=${player}&b=${incumbent}&team=${team}`,
    "compare",
    "Percentiles side by side",
  );
  await shoot(page, "/backtest", "backtest", "By club");
  await shoot(page, "/methodology", "methodology", "Known limitations");
} finally {
  await browser.close();
  server?.kill();
}
