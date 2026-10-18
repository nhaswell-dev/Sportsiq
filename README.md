# SportsIQ

Offline-first NFL and NBA schedule normalization. Milestone 2B.5 connects explicit live BALLDONTLIE imports to Milestone 2B's SQLite validation, UPSERTs, and change history. The default remains local fixtures; there is no trading or market integration.

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

## Persistent schedules (Milestone 2B, offline only)

    .venv/bin/python -m sportsiq import-schedule --provider balldontlie --fixture tests/fixtures/stored_schedules.json
    .venv/bin/python -m sportsiq stored-schedule --league nfl --date 2026-10-18
    .venv/bin/python -m sportsiq stored-schedule --league nba --date 2026-10-21
    .venv/bin/python -m sportsiq stale-schedules --hours 24

All three commands accept `--database PATH`; the default is project-root `data/sportsiq.sqlite3`, independent of the working directory. Parent directories and tables are created automatically. Stored queries accept optional `--league`, `--provider`, and UTC `--date`; stale reports accept optional `--league`, `--provider`, and an aware ISO 8601 `--now` for reproducibility. An absent database is initialized empty. Output is JSON; validation failures exit with code 2 and a record number/field error.

Import files must be normalized JSON arrays shaped like the existing `schedule` output, not raw ESPN, NBA, or BALLDONTLIE responses. See the synthetic mixed-league `tests/fixtures/stored_schedules.json`. Each record requires `league`, `provider_ids`, `home`, `away`, `start_time`, and `status`. The explicit `--provider` selects a namespace present in the game and both team ID maps (`espn` for the NFL fixture parser, `balldontlie` for the NBA fixture parser and live adapters). IDs must already be nonempty strings. Teams require distinct source IDs and nonblank names; abbreviations are optional strings. Invalid/missing IDs, incomplete teams, invalid statuses, and missing/malformed/naive timestamps reject the entire batch. Valid statuses are `scheduled`, `in_progress`, `final`, `postponed`, `canceled`, `delayed`, `suspended`, `abandoned`, and the explicit domain value `unknown`. Unrecognized input is not silently converted to `unknown` by storage. Existing provider normalization is unchanged.

`--retrieved-at 2026-10-18T12:00:00Z` optionally supplies the actual observation time when importing saved data; otherwise import time is used. This is not the game's start time or a provider last-modified timestamp. Replaying old data without its original retrieval time will mark it freshly observed, so supply it for archived snapshots. Stale means `retrieved_at < now - hours` (default 24 hours), across all statuses; equality is fresh. This is an operator threshold, not a provider SLA.

SQLite uses a `games` table with scalar league, provider, provider game ID, home/away IDs/names/optional abbreviations, UTC start, status, retrieval time, and creation/update times. `UNIQUE(league, provider, provider_game_id)` and parameterized UPSERTs prevent duplicates. `created_at` is first insertion time; `updated_at` changes only when game fields change; `retrieved_at` advances on unchanged reimports too. All timestamps are ISO 8601 UTC with fixed microsecond precision. Older observations are rejected atomically rather than regressing current state. The imported count is input records processed, not new rows inserted.

Every material update, including team corrections, postponements, start-time changes, and explicit cancellations, appends old/new game snapshots to `game_changes` in the same transaction. Unchanged observations do not create history. Missing games or empty imports never imply cancellation. Rows and history are retained indefinitely with no pruning, deletion command, raw-response archive, or automatic refresh. Keep local backups outside Git; database/sidecar/temp files, `.env`, and `.env.save` are ignored, not deleted. SQLite is local research storage, not a cross-provider team registry. Detailed schema and retention semantics are in `docs/architecture.md`.

The existing `schedule` command remains read-only and does not write the database. These three offline storage commands never read credentials or contact an API. PostgreSQL remains out of scope.

## Explicit live schedule ingestion (Milestone 2B.5)

From the project root, import one league and UTC date at a time:

    .venv/bin/python -m sportsiq import-live-schedule --league nfl --date 2026-10-18
    .venv/bin/python -m sportsiq import-live-schedule --league nba --date 2026-10-21 --database data/sportsiq.sqlite3

Both `--league nfl|nba` and `--date YYYY-MM-DD` are required; the provider is always BALLDONTLIE. Credentials use the same project-root `.env` loader described below, never command-line arguments. The default database is `/home/hermesdev/development/sportsiq/data/sportsiq.sqlite3` in this checkout (project-root `data/sportsiq.sqlite3` elsewhere). `--database PATH` overrides it; relative overrides are relative to the working directory.

The date means the half-open UTC interval `[00:00:00, next day 00:00:00)`, not provider-local date. The shared adapter queries previous/current/next provider dates and follows all cursor pages before opening SQLite. Provider start-time instants are preserved, converted to UTC rather than moved onto the requested date. Excluded out-of-day records are reported in JSON `excluded` with provider game ID, original `source_timestamp`, UTC `start_time`, and reason; they are not persisted or treated as cancellations. Original offset spelling/raw payloads are not archived. Records with missing/naive/malformed starts or invalid teams fail the collection, including malformed out-of-day records.

All retained games pass the existing storage validator before database access. The existing transaction, parameterized UPSERT, identity constraint, and change-history operations are reused without schema changes. Repeated imports refresh observation time without duplicating rows/history; changes update the same row and append history atomically. A failure on a later API page writes nothing, and database failures roll back the batch and history. Missing games never imply cancellation. `retrieved_at` is the UTC time collection/validation finished, distinct from the provider start time; no provider last-modified value is invented.

JSON output reports `league`, `date`, `provider`, `dry_run`, `complete`, successful `pages`, unique retained `validated` count, `imported` count, exclusions, and retrieval time. `imported` counts processed records, not new rows. Completion means cursor traversal finished, not a guarantee of the provider's real-world schedule coverage. Missing/malformed metadata, full pages without a terminal/continuation cursor, invalid cursors/cycles, malformed records, transport/JSON errors, and HTTP failures abort with sanitized CLI errors (exit 2). Short pages with an empty metadata object are terminal. Normal imports retain the existing timeout, throttling, and bounded 429/5xx retries.

### Safe manual verification

First run the complete offline suite above. Only after it passes, use dry-run mode to fetch/normalize/validate without opening, creating, or modifying any database, directory, schema, row, or history:

    .venv/bin/python -m sportsiq import-live-schedule --league nfl --date 2026-10-18 --dry-run --single-request
    .venv/bin/python -m sportsiq import-live-schedule --league nba --date 2026-10-21 --dry-run --single-request

`--single-request` is allowed only with `--dry-run`: it disables retries and stops after the first page, limiting each invocation to at most one HTTP request. If a next cursor exists, JSON says `complete: false`; this is partial verification only, not a complete schedule. Stop on any error; do not rerun to spend additional requests during a capped verification. `--dry-run` without `--single-request` follows all pages and allows normal retries, so it is not suitable for a one-request budget. Do not run simultaneous quota consumers. Inspect only summary counts, never headers, keys, or raw response bodies. A successful dry-run requires a separate explicit invocation without `--dry-run` to persist anything. No jobs, cron, automatic ingestion, or trading are configured.

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
- `sportsiq/storage/schedule.py`: validated SQLite imports, source-scoped games, change history, stored queries, and stale reports.
- `sportsiq/analysis/`, `sportsiq/reports/`: reserved modules for future milestones, currently empty.
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
