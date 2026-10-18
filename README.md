# SportsIQ

Offline-first NFL schedule normalization for a future sports analytics and Kalshi research application. Milestone 1 only parses local JSON; it has no live HTTP client, credentials, trading commands, or market integration.

## Requirements

Python 3.12+; no runtime or test dependencies beyond the standard library. The local `.venv` uses system Python 3.12 and was created without pip because `ensurepip` is unavailable on this host. It is separate from Hermes and global Python.

## Tests

From the project root:

    .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

On another machine, create a local environment with `python3 -m venv .venv` first. If `ensurepip` is unavailable, `python3 -m venv --without-pip .venv` is sufficient for Milestone 1.

## Sample schedule query (offline fixture)

    .venv/bin/python -m sportsiq schedule --date 2026-09-13 --fixture tests/fixtures/nfl_scoreboard.json

The fixture is synthetic ESPN-shaped data, not a captured live response or an actual NFL schedule. Dates passed to the CLI are UTC calendar dates. `Game.start_time` is always timezone-aware and converted to UTC. IDs remain namespaced by provider; no game/market joins are attempted. The adapter consumes a `ScoreboardSource` protocol so it can be tested without making HTTP requests.

## Provider evaluation (reviewed October 18, 2026)

**nflverse — historical research candidate.** Its play-by-play loader covers available seasons since 1999 and supports CSV and Parquet as well as RDS; its releases provide other game, player, and team research datasets.[3] The published in-season cadence is approximately every five minutes for game/schedule data, with processed play-by-play and player/team stats refreshed nightly after game days and at other game-day points. These are stated pipeline schedules, not a guarantee that a particular release is complete or up to date; midweek stat corrections can require a later refresh.[2] The nflverse organization says most release data is CC BY 4.0, while FTN data is CC BY-SA 4.0 as of October 2026. Check the license and attribution requirements of each selected dataset/release, including any upstream rights, before ingestion or redistribution.[1] Future integration should record the release URL, version/asset time, fetch time, source license, and attribution with each snapshot. No nflverse download is implemented yet.

**BALLDONTLIE NFL — current schedule candidate.** The documented `GET /nfl/v1/games` endpoint returns game records and supports date, season, week, team, and season-type filters; the default season types exclude preseason. It uses cursor pagination (`meta.next_cursor`), with 25 results per page by default and a maximum of 100.[4] An API key is required even for the free tier. NFL Games, Teams, and Players are free-tier endpoints; Stats and other listed premium datasets are not. The free tier is limited to 5 requests per minute. The NFL docs describe in-progress game updates as real-time but provide no guaranteed schedule-publishing or refresh interval; the API-wide "2002-current" statement does not guarantee complete coverage of every field or season.[4] The September 17, 2026 terms permit certain lawful commercial uses while restricting competing services, unmodified data resale, credential sharing, and bypassing tier/rate controls; they disclaim data timeliness and accuracy guarantees.[5] Future integration needs a separately approved account/key (never committed), entitlement check, conservative rate limiting, cursor handling, error/retry policy, provider-specific IDs, timestamp normalization, and last-observed/last-fetched timestamps. No authenticated requests are made by this project.

**Provider boundary.** Keep `Game`/`Team` independent of source format. A future nflverse importer should handle historical snapshots; a separate BALLDONTLIE schedule adapter should implement `ScheduleProvider` through an injected read-only client. Do not assume identifiers match across providers: maintain explicit, auditable team/game crosswalks and retain source IDs. The existing ESPN-shaped parser remains fixture-only. Disney's terms covering ESPN restrict automated access/extraction without express written permission, and this parser has no supported public scoreboard schema contract.[6] No live ESPN URL or transport is enabled.

**Kalshi boundary.** Kalshi documents unauthenticated public market-data endpoints, but no Kalshi integration exists in this milestone. Any future implementation must be separately scoped to read-only research, with no order placement or trading functions.[7]

## Dependency and integration decisions

The current `.venv` has no pip because system Python lacks `ensurepip`. Milestone 1 and 1.5 have no third-party runtime or test dependencies, so pip is not required and `pyproject.toml` remains unchanged. Before a later milestone that actually needs dependencies, choose a project-local Python environment/package workflow; do not install into global Python or Hermes. BALLDONTLIE access requires approval to create/use an account and securely supply a key, even on the free tier. Confirm nflverse dataset selection and licensing/attribution before download. Neither integration is active yet.

## Structure

- `sportsiq/domain/`: normalized game/team models.
- `sportsiq/providers/`: schedule contract, fixture-only ESPN-shaped parser, local fixture source.
- `sportsiq/storage/`, `sportsiq/analysis/`, `sportsiq/reports/`: reserved modules for future milestones, currently empty.
- `sportsiq/cli.py`: offline schedule query.
- `tests/`: mocked-source unit tests and synthetic JSON fixture.

## Sources

[1] https://github.com/nflverse
[2] https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html
[3] https://nflreadr.nflverse.com/reference/load_pbp.html
[4] https://nfl.balldontlie.io
[5] https://www.balldontlie.io/terms.html
[6] https://disneytermsofuse.com/english
[7] https://docs.kalshi.com/getting_started/quick_start_market_data
