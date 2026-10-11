# ADR-0002: ESPN instead of FotMob for team possession

- Status: Accepted
- Date: 2026-10-11
- Decider: build agent (owner-requested audit session on the owner's machine)

## Context
Possession is used in two places: it possession-adjusts defensive volume KPIs (PRD §8.4,
CLAUDE.md rule 9) and it is one of the three StyleFit team-style features. PRD §7.1 named
FotMob (Tier 1b), fetched through `soccerdata`.

The first live ingest on the owner's machine (2026-10-11) showed the FotMob adapter could
never have worked with the pinned dependency. `soccerdata` 1.9.0 (April 2026) **removed its
FotMob reader at FotMob's request** (release notes: "Removed support for scraping FotMob
following their request"). `soccerdata.FotMob` raised `AttributeError`, which also escaped
the ingest runner and stopped `scout demo` (fixed separately). Pinning `soccerdata` 1.8.x
would scrape a site that has asked not to be scraped, against the project's own scraping
etiquette (CLAUDE.md rule 11). It would also bring back the Understat endpoints that 1.9
replaced.

Without possession every defensive KPI falls back to "unadjusted", and StyleFit loses one
of its three dimensions.

## Decision
Take possession from ESPN's public scoreboard JSON
(`site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard?dates=YYYYMMDD`). Each
finished match lists both teams' `possessionPct`. `ingest/espn.py` asks for the season's
calendar once, then requests one scoreboard per match day up to today, about 115 requests
for a full season at 0.5 requests/s. It goes through `PoliteClient` (rate limit, User-Agent,
retries, interstitial detection) like the FPL adapter, so it needs no third-party scraper.

Its output matches the FotMob frame (team, opponent, both shares; missing stays missing;
shares must sum to 1 within the configured tolerance). It keys matches by ESPN's stable
event id and states home and away explicitly. Migration 0005 replaces
`dim_match.fotmob_game` with `dim_match.espn_event_id`. The FotMob adapter, fixtures and
config are removed. `soccerdata` stays for Understat.

## Alternatives considered
- **Pin `soccerdata` 1.8.8 for FotMob:** works today, but disregards FotMob's request and
  regresses Understat. Rejected.
- **`soccerdata.ESPN.read_matchsheet`:** the same data, but it fetches every match day *and*
  one summary per match (about 3x the requests), and caches outside `data/raw`. Rejected.
- **No possession (always "unadjusted"):** honest, but it drops PRD §8.4 for every KPI it
  covers and weakens StyleFit. Kept only as the fallback when ESPN is unavailable.
- **WhoScored / Sofascore through `soccerdata`:** need Selenium or TLS fingerprint
  workarounds and target sites that actively block scrapers. Rejected.

## Consequences
- Defensive KPIs are possession-adjusted again on real data, and StyleFit has all three
  features.
- ESPN's endpoint is public but undocumented, so it could change without notice. The
  adapter's contract tests fail loudly on a schema change (missing `events`,
  `competitions`, home/away sides), and a failed ESPN ingest only marks KPIs "unadjusted".
- Personal, non-commercial use only, like every other source. Raw responses stay in
  `data/raw/espn` (gitignored).
- PRD §7.1's Tier 1b row now reads ESPN (this ADR overrides the PRD where they differ).
