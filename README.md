# SportsIQ

Offline-first NFL and NBA schedule normalization. Milestone 2A adds opt-in, read-only BALLDONTLIE Games requests. The default remains local fixtures; there is no trading or market integration.

## Requirements

Python 3.12+; no runtime or test dependencies beyond the standard library. Use the project-local `.venv`, separate from Hermes and global Python.

## Tests

From the project root:

    .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

On another machine, create a local environment with `python3 -m venv .venv` first. If `ensurepip` is unavailable, `python3 -m venv --without-pip .venv` suffices.

## Sample schedule queries (offline fixtures)

    .venv/bin/python -m sportsiq schedule --league nfl --date 2026-09-13 --fixture tests/fixtures/nfl_scoreboard.json
    .venv/bin/python -m sportsiq schedule --league nba --date 2026-10-21 --fixture tests/fixtures/nba_games.json

`--league` defaults to `nfl`, so the original command without it still works. Both fixtures are synthetic and contain no actual games. Dates passed to the CLI are UTC calendar dates: the NBA fixture deliberately has a local October 20 start that becomes October 21 in UTC. `Game.start_time` is timezone-aware and normalized to UTC; missing or naive NBA tipoff times are rejected. Provider IDs remain string-valued and namespaced by provider, with an explicit `league` and normalized `status`. The NFL fixture omits status, so its output is `unknown`. No cross-provider game/market joins are attempted. See `docs/architecture.md` for model and adapter boundaries.

## Opt-in BALLDONTLIE Games (read-only)

Put `BALLDONTLIE_API_KEY=your-key` in the project-root `.env` file; do not commit it or a backup. The app reads only that file at runtime (not shell-wide environment variables). Protect the file with local filesystem permissions. Do not pass the key on the CLI. Only the official `https://api.balldontlie.io` host receives its Authorization header; redirects are disabled. Both Games endpoints are free-tier eligible, but an account/key and entitlement are required.

    .venv/bin/python -m sportsiq schedule --provider balldontlie --league nfl --date 2026-10-18
    .venv/bin/python -m sportsiq schedule --provider balldontlie --league nba --date 2026-10-18

The required `--date` is a UTC day. Each request explicitly filters three provider dates (previous, selected, next) to catch date rollovers, then retains only games whose timezone-aware start falls on the selected UTC day. Missing or naive game start times fail rather than invent a time. Pages use `per_page=100` and `meta.next_cursor`; duplicates and repeated cursors are rejected/deduplicated. Requests have a 10-second timeout, process-local minimum 12.1-second interval (free-tier maximum five requests/minute), and at most two retries for HTTP 429/5xx. An excessive Retry-After fails safely. The interval does not coordinate separate processes or other users of the same key: leave quota headroom when sharing an account. No stats, odds, or paid endpoint is used. HTTP/parse errors are sanitized rather than displaying provider response bodies or credentials.

## Provider evaluation (reviewed October 18, 2026)

**nflverse — historical research candidate.** Its play-by-play loader covers available seasons since 1999 and supports CSV and Parquet as well as RDS; its releases provide other game, player, and team research datasets.[3] The published in-season cadence is approximately every five minutes for game/schedule data, with processed play-by-play and player/team stats refreshed nightly after game days and at other game-day points. These are stated pipeline schedules, not a guarantee that a particular release is complete or up to date; midweek stat corrections can require a later refresh.[2] The nflverse organization says most release data is CC BY 4.0, while FTN data is CC BY-SA 4.0 as of October 2026. Check the license and attribution requirements of each selected dataset/release, including any upstream rights, before ingestion or redistribution.[1] Future integration should record the release URL, version/asset time, fetch time, source license, and attribution with each snapshot. No nflverse download is implemented yet.

**BALLDONTLIE NFL — opt-in current schedule.** The documented `GET /nfl/v1/games` endpoint supports date, season, week, team, and season-type filters; default season types exclude preseason. It uses cursor pagination (`meta.next_cursor`), with 25 results per page by default and a maximum of 100.[4] An API key is required even for the free tier. Games is free-tier eligible; Stats and other premium datasets are not. The free tier is limited to 5 requests per minute. The NFL docs describe in-progress updates as real-time but provide no guaranteed schedule-publishing interval or historical completeness.[4] The terms restrict competing services, unmodified data resale, credential sharing, and bypassing tier/rate controls; they disclaim timeliness and accuracy guarantees.[5]

**BALLDONTLIE NBA — opt-in current schedule.** The official NBA OpenAPI specification lists `GET /nba/v1/games` (dates, seasons, team IDs and season-type filters), cursor pagination (25 default, 100 maximum), and an API-wide historical coverage claim. Games is free-tier eligible, requires an API key, and permits 5 requests per minute; player stats and advanced stats require paid entitlements.[8] The provider gives no guaranteed schedule refresh interval or historical completeness per season. Permission to use Games does not grant access to paid endpoints.[5]

**Historical NBA options (separate decision).** BALLDONTLIE's broad NBA date-range claim is a possible historical-games source but is not proof of complete historical game/player coverage, and historical player stats are not in the free tier.[8] SportsDataIO documents a licensed NBA API and a historical Vault for prior-season team/player/game data; the exact years and fields vary by league and product, and its commercial license must cover the planned storage, modeling, and report/display use.[9][10][11] Neither source is approved for ingestion by this milestone. A data-access contract, dataset selection, coverage sample, licensing review, and cost decision are needed first.

**Provider boundary.** Keep `Game`/`Team` independent of source format and include `league` before any cross-provider match. The opt-in BALLDONTLIE adapters share a restricted read-only client; the NBA fixture parser remains synthetic. Do not assume identifiers match across providers or leagues. The ESPN-shaped NFL parser remains fixture-only; no live ESPN URL or transport is enabled.[6]

**Kalshi boundary.** Kalshi documents unauthenticated public market-data endpoints, but no Kalshi integration exists in this milestone. Any future implementation must be separately scoped to read-only research, with no order placement or trading functions.[7]

## Dependency and integration decisions

The project-local `.venv` has no pip because system Python lacks `ensurepip`; the standard-library HTTP client needs no additional dependencies. BALLDONTLIE access requires an approved account and entitlement even on the free tier. Historical provider licensing and entitlements remain separate decisions.

## Structure

- `sportsiq/domain/`: shared `Game`, `Team`, `League`, and `GameStatus` types.
- `sportsiq/providers/`: schedule contract, fixture parsers, local JSON source, opt-in BALLDONTLIE Games client/adapters.
- `sportsiq/storage/`, `sportsiq/analysis/`, `sportsiq/reports/`: reserved modules for future milestones, currently empty.
- `sportsiq/cli.py`: offline-default, opt-in BALLDONTLIE league-selectable schedule query.
- `tests/`: five original NFL tests plus multi-sport/NBA tests and synthetic JSON fixtures.
- `docs/architecture.md`: source boundaries, historical-data options and future read-only matching.

## Sources

[1] https://github.com/nflverse
[2] https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html
[3] https://nflreadr.nflverse.com/reference/load_pbp.html
[4] https://nfl.balldontlie.io
[5] https://www.balldontlie.io/terms.html
[6] https://disneytermsofuse.com/english
[7] https://docs.kalshi.com/getting_started/quick_start_market_data
[8] https://nba.balldontlie.io
[9] https://sportsdata.io/help/data-rights-and-licensing-questions
[10] https://sportsdata.io/help/historical-data-integration-guide
[11] https://sportsdata.io/developers/api-documentation/nba
[12] https://www.balldontlie.io/openapi/nfl.yml
[13] https://www.balldontlie.io/openapi/nba.yml
