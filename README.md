# SportsIQ

Offline-first NFL and NBA schedule normalization for a future sports analytics and Kalshi research application. Milestone 1.6 parses local JSON fixtures only; it has no live HTTP client, credentials, trading commands, or market integration.

## Requirements

Python 3.12+; no runtime or test dependencies beyond the standard library. The local `.venv` uses system Python 3.12 and was created without pip because `ensurepip` is unavailable on this host. It is separate from Hermes and global Python.

## Tests

From the project root:

    .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

On another machine, create a local environment with `python3 -m venv .venv` first. If `ensurepip` is unavailable, `python3 -m venv --without-pip .venv` is sufficient for Milestone 1.6.

## Sample schedule queries (offline fixtures)

    .venv/bin/python -m sportsiq schedule --league nfl --date 2026-09-13 --fixture tests/fixtures/nfl_scoreboard.json
    .venv/bin/python -m sportsiq schedule --league nba --date 2026-10-21 --fixture tests/fixtures/nba_games.json

`--league` defaults to `nfl`, so the original command without it still works. Both fixtures are synthetic and contain no actual games. Dates passed to the CLI are UTC calendar dates: the NBA fixture deliberately has a local October 20 start that becomes October 21 in UTC. `Game.start_time` is timezone-aware and normalized to UTC; missing or naive NBA tipoff times are rejected. Provider IDs remain string-valued and namespaced by provider, with an explicit `league` and normalized `status`. The NFL fixture omits status, so its output is `unknown`. No cross-provider game/market joins are attempted. See `docs/architecture.md` for model and adapter boundaries.

## Provider evaluation (reviewed October 18, 2026)

**nflverse — historical research candidate.** Its play-by-play loader covers available seasons since 1999 and supports CSV and Parquet as well as RDS; its releases provide other game, player, and team research datasets.[3] The published in-season cadence is approximately every five minutes for game/schedule data, with processed play-by-play and player/team stats refreshed nightly after game days and at other game-day points. These are stated pipeline schedules, not a guarantee that a particular release is complete or up to date; midweek stat corrections can require a later refresh.[2] The nflverse organization says most release data is CC BY 4.0, while FTN data is CC BY-SA 4.0 as of October 2026. Check the license and attribution requirements of each selected dataset/release, including any upstream rights, before ingestion or redistribution.[1] Future integration should record the release URL, version/asset time, fetch time, source license, and attribution with each snapshot. No nflverse download is implemented yet.

**BALLDONTLIE NFL — current schedule candidate.** The documented `GET /nfl/v1/games` endpoint returns game records and supports date, season, week, team, and season-type filters; the default season types exclude preseason. It uses cursor pagination (`meta.next_cursor`), with 25 results per page by default and a maximum of 100.[4] An API key is required even for the free tier. NFL Games, Teams, and Players are free-tier endpoints; Stats and other listed premium datasets are not. The free tier is limited to 5 requests per minute. The NFL docs describe in-progress game updates as real-time but provide no guaranteed schedule-publishing or refresh interval; the API-wide "2002-current" statement does not guarantee complete coverage of every field or season.[4] The September 17, 2026 terms permit certain lawful commercial uses while restricting competing services, unmodified data resale, credential sharing, and bypassing tier/rate controls; they disclaim data timeliness and accuracy guarantees.[5] Future integration needs a separately approved account/key (never committed), entitlement check, conservative rate limiting, cursor handling, error/retry policy, provider-specific IDs, timestamp normalization, and last-observed/last-fetched timestamps. No authenticated requests are made by this project.

**BALLDONTLIE NBA — candidate for current schedules, not yet connected.** The official NBA docs list `GET /v1/games` (dates, seasons, team IDs and season-type filters), cursor pagination (25 default, 100 maximum), and an API-wide "1946-current" coverage claim. The free tier includes Teams, Players and Games, requires an account/API key, and permits 5 requests per minute; Game Player Stats are ALL-STAR/GOAT only, while Season Averages and Game Advanced Stats are GOAT only.[8] The Games section calls in-progress data realtime but states no guaranteed schedule refresh interval or historical completeness per season; quarter scores, bonus and timeouts are available only from the 2023 season onward.[8] The provider's terms restrict competing products, resale of unmodified data, and sharing credentials; permission to use data does not grant access to paid endpoints.[5] No authentication or live request is part of Milestone 1.6.

**Historical NBA options (separate decision).** BALLDONTLIE's broad NBA date-range claim is a possible historical-games source but is not proof of complete historical game/player coverage, and historical player stats are not in the free tier.[8] SportsDataIO documents a licensed NBA API and a historical Vault for prior-season team/player/game data; the exact years and fields vary by league and product, and its commercial license must cover the planned storage, modeling, and report/display use.[9][10][11] Neither source is approved for ingestion by this milestone. A data-access contract, dataset selection, coverage sample, licensing review, and cost decision are needed first.

**Provider boundary.** Keep `Game`/`Team` independent of source format and include `league` before any cross-provider match. A future nflverse importer should handle historical NFL snapshots; separate BALLDONTLIE NFL/NBA schedule adapters should implement `ScheduleProvider` through injected read-only clients only after approval. The current NBA parser consumes a synthetic BALLDONTLIE-shaped local fixture, not an API response. Do not assume identifiers match across providers or leagues: maintain explicit, auditable team/game crosswalks and retain source IDs. The existing ESPN-shaped NFL parser remains fixture-only. Disney's terms covering ESPN restrict automated access/extraction without express written permission, and this parser has no supported public scoreboard schema contract.[6] No live ESPN URL or transport is enabled.

**Kalshi boundary.** Kalshi documents unauthenticated public market-data endpoints, but no Kalshi integration exists in this milestone. Any future implementation must be separately scoped to read-only research, with no order placement or trading functions.[7]

## Dependency and integration decisions

The current `.venv` has no pip because system Python lacks `ensurepip`. Milestones 1–1.6 have no third-party runtime or test dependencies, so pip is not required and `pyproject.toml` remains unchanged. Before a later milestone that actually needs dependencies, choose a project-local Python environment/package workflow; do not install into global Python or Hermes. BALLDONTLIE NFL/NBA access requires separate approval to create/use an account and securely supply a key, even on the free tier. Confirm nflverse dataset selection and licensing/attribution before download. Confirm NBA historical provider licensing and entitlements before ingestion. No live integration is active yet.

## Structure

- `sportsiq/domain/`: shared `Game`, `Team`, `League`, and `GameStatus` types.
- `sportsiq/providers/`: schedule contract, fixture-only ESPN-shaped NFL parser, fixture-only BALLDONTLIE-shaped NBA parser, local JSON source.
- `sportsiq/storage/`, `sportsiq/analysis/`, `sportsiq/reports/`: reserved modules for future milestones, currently empty.
- `sportsiq/cli.py`: offline league-selectable schedule query.
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
