# SportsIQ architecture (Milestone 2C)

## Current execution boundary

The default `sportsiq schedule --league nfl|nba --date YYYY-MM-DD --fixture PATH` reads local synthetic JSON. Explicit `--provider balldontlie` instead reads the project `.env` key and uses the official BALLDONTLIE Games endpoint for that league; it rejects `--fixture`. Both return normalized JSON for the requested UTC day without database writes. The NFL default and all existing fixture commands remain unchanged. New offline storage commands operate only on normalized local files and SQLite; they never construct a network client or read credentials. Separate opt-in Kalshi market-data discovery is described below; there are no trading actions or live ESPN requests.[6]

## Shared domain

### Required target scope versus implemented scope

The required target is FOUR leagues: NFL, NBA, NCAAF college football, and NCAAB college basketball. The schedule `League`, schedule CLI choices, BALLDONTLIE provider paths, and SQLite CHECK constraint remain NFL/NBA only. Separate parlay discovery records classify the four known Kalshi game-winner series without expanding schedule persistence. College schedule support remains a future explicit adapter/domain/schema change. Record division, season, and men's/women's competition in the future coverage contract; source-specific college coverage is not universal NCAA coverage.

`Game` has a `League` (`nfl`/`nba`), `GameStatus`, timezone-aware `start_time`, home/away `Team` values, and string-valued provider-ID maps. `Team` supports an optional abbreviation. Both fixture parsers convert aware starts to UTC and use `unknown` status when the fixture has no recognized lifecycle state. The NFL parser gives recognized specific status names (including postponed and canceled) precedence over broad pre/in/post states; unfamiliar names stay unknown rather than being mislabeled. The legacy four-positional-argument `Game` constructor defaults to NFL and unknown status; all new adapters must pass the league explicitly. The CLI's `--date` means UTC calendar day, not the provider's local game date. A future provider must not guess a missing NBA tipoff timestamp or treat a naive timestamp as local time.

Use `(league, provider, provider_id)` as a source-scoped identity; do not join ESPN, BALLDONTLIE, nflverse, and Kalshi records just because names or dates resemble each other. Crosswalks should have review state, evidence, and versioned validity periods. Storage preserves game start separately from retrieval and material-write timestamps.

## Provider contracts and proposed stages

- `ScheduleProvider.games_on(day)` returns normalized `Game` records. Source protocols keep fixture parsing independent of HTTP. `ESPNNFLScheduleProvider` and `NBAFixtureScheduleProvider` remain offline. `BALLDONTLIEGamesProvider` selects the NFL or NBA Games endpoint through an injected `GamesClient`, normalizes IDs, lifecycle, teams and aware UTC starts, and rejects malformed records.
- NFL historical candidate: nflverse release snapshots with dataset-specific attribution/license metadata. Its published update schedule does not guarantee that any given asset is complete or fresh; the FTN share-alike exception needs review before use.[1][2]
- BALLDONTLIE Games client: constant HTTPS host and NFL/NBA paths; disabled redirects; project-local `.env` key only in Authorization; sanitized failures. UTC date queries cover adjacent provider dates and filter normalized UTC times; `per_page=100`, cursor cycle detection and ID deduplication cover pagination. Default timeout is 10 seconds, with a process-local 12.1-second request interval and at most two 429/5xx retries honoring Retry-After up to 60 seconds. Separate processes and other users of the key are not coordinated, so do not run concurrent quota consumers. The free tier allows Games, not paid stats.[4][8]
- NBA historical research is a separate licensing choice: BALLDONTLIE offers an API-wide history claim but no guarantee of complete old box scores or player stats; historical player stats need a paid tier.[8] SportsDataIO offers NBA feeds and a historical Vault under a use-case-specific license; actual NBA years/fields, pricing, storage, model training and report rights require confirmation before selection.[9][10][11]

## SQLite schedule storage

Milestone 2B.5 adds only explicit orchestration: `import-live-schedule --league nfl|nba --date YYYY-MM-DD [--database PATH] [--dry-run [--single-request]]`. It loads the existing project-local key, constructs the existing `GamesClient` and `BALLDONTLIEGamesProvider`, and calls `collect_on` for normalized games, excluded source timestamps, successful page count, and cursor-completion state. `games_on` remains the list-returning schedule interface, using the same collection/normalization path. There is no second HTTP client, scheduler, or schema migration.

Collection finishes and retained records pass `validate_record` before opening `ScheduleStore`; `import_records` revalidates and performs its existing atomic transaction. The default location remains project-root `data/sportsiq.sqlite3`. Source instants become UTC without changing the actual game time; out-of-UTC-day records are reported, not persisted or coerced onto the queried date. Original offset strings appear in exclusion reports; raw responses are not archived. Retrieval time is captured after collection/validation. Errors on any page prevent all persistence; transaction failures roll back games and history together.

Dry runs never instantiate `ScheduleStore`, including for an existing database. `--single-request` requires dry-run, disables HTTP retries, and sets a one-page collection limit. A remaining cursor yields `complete: false` with validated partial counts and zero imports; regular ingestion traverses all pages or fails. Completion describes the response cursor chain, not guaranteed source coverage. Metadata must be an object; a full page needs an explicit next/terminal cursor (using the returned `per_page` when present). Short pages with empty metadata remain compatible terminal responses. Existing cursor-cycle checks, throttling, timeout, bounded retries, transport/JSON sanitization, and ID deduplication are reused; partial HTTP reads also become sanitized failures. See the README's safe manual verification procedure before any live request.

`sportsiq/storage/schedule.py` owns standard-library `sqlite3` persistence. Default location: project-root `data/sportsiq.sqlite3`; each storage command accepts `--database PATH`. No dependencies, PostgreSQL, Docker, or external services are added. Tables are initialized on first open; no prior persistent schema exists to migrate in this milestone.

Schema (all fields NOT NULL except optional abbreviations):

| Table | Columns and constraints |
| --- | --- |
| `games` | `id INTEGER PRIMARY KEY`; `league TEXT CHECK IN ('nfl','nba')`; `provider TEXT`; `provider_game_id TEXT`; `home_id TEXT`; `home_name TEXT`; `home_abbreviation TEXT NULL`; `away_id TEXT`; `away_name TEXT`; `away_abbreviation TEXT NULL`; `start_time TEXT`; `status TEXT` constrained to the nine domain statuses; `retrieved_at TEXT`; `created_at TEXT`; `updated_at TEXT`; `UNIQUE(league, provider, provider_game_id)` |
| `game_changes` | `id INTEGER PRIMARY KEY`; `game_id INTEGER REFERENCES games(id)`; `before_json TEXT`; `after_json TEXT`; `retrieved_at TEXT`; `changed_at TEXT` |

Game rows are normalized, source-scoped schedule records, with scalar team fields rather than embedded provider payloads. Team IDs are scoped by the row's league/provider; no global team identity/crosswalk is inferred. Names and abbreviations are per-game observations so corrections cannot rewrite unrelated games. History snapshots contain the eleven material game fields (league/provider/game ID, both team IDs/names/abbreviations, start, status), not full raw responses. Foreign-key enforcement is enabled on each connection.

`import-schedule --provider NAME --fixture PATH [--retrieved-at ISO8601]` reads a normalized JSON array compatible with existing `schedule` output. The fixture may contain both leagues. It validates each record and the entire envelope before writes; a batch is atomic, including history. IDs/names/provider must be nonblank strings, each team must have a provider ID, home/away IDs must differ, and optional abbreviations must be nonblank strings when present. League/status must match the domain enums, including explicit `unknown`; malformed values are rejected with record/field context rather than coerced. Valid offset timestamps are normalized to UTC; naive, missing, or invalid timestamps fail. Unknown additional input fields/other provider IDs are not persisted. Existing adapters retain their original normalization behavior.

Writes use bound SQL parameters and `INSERT ... ON CONFLICT ... DO UPDATE`, never replacement/deletion. A `BEGIN IMMEDIATE` transaction serializes observation comparison, history, and upsert. Same-identity inputs update the existing row, including within a batch; input order resolves equal-retrieval-time changes. Retrieval times older than the current row are rejected with rollback of the whole batch. A material change appends before/after snapshots and its retrieval/change times. Unchanged reimports only refresh `retrieved_at`; they do not bump `updated_at` or append history. `created_at`/`updated_at` are local insertion/material-write times; retrieval is the supplied actual observation time (default local import time), separate from provider game start. No provider last-modified value is inferred. All stored timestamps use fixed-width UTC ISO 8601 microseconds for consistent ordering.

`stored-schedule [--league nfl|nba] [--provider NAME] [--date YYYY-MM-DD]` filters stored rows on a half-open UTC day and emits flat JSON rows including database IDs and timestamps. `stale-schedules --hours 24 [--now ISO8601] [--league nfl|nba] [--provider NAME]` reports rows whose retrieval time is strictly older than the cutoff; all lifecycle statuses are eligible. The cutoff must be finite and nonnegative; it does not compare game start or material-update time. Both commands initialize a missing database empty. `ScheduleStore.history(game_id)` exposes ordered decoded snapshots for local programmatic inspection; no history CLI is added.

Retention: current games and material changes are kept indefinitely, including cancellations. Absence from any response/fixture is not evidence of cancellation; only an explicit status update changes lifecycle state. There is no deletion, pruning, raw-response storage, scheduler, automatic live persistence, or retention policy enforcement. Archived fixture replay must supply its actual retrieval time to avoid false freshness. The database is rebuildable local research state and must be backed up locally if its history matters. Database files/SQLite sidecars, temporary files, `.env`, and `.env.save` are ignored by Git; existing backups are never removed. Licensing/storage rights for future real datasets remain a separate approval gate.

## Kalshi parlay discovery (Milestone 2C)

`providers/kalshi.py` owns strict URL parsing, a GET-only fixed-origin public client, and reusable extraction. `domain/parlay.py` holds separate discovery records; `reports/parlay.py` renders terminal-safe summaries. `kalshi-parlay --url URL --offline FIXTURE|--live [--format json|summary] [--no-retries]` never loads credentials or constructs schedule storage. No shared schedule enum/schema change is needed. The client limits bytes, timeouts, retries, and total HTTP attempts; all tests inject transport or use synthetic fixtures. See `kalshi-parlay.md` for exact limits, API references, fixture schema, source-field provenance and the reference-combo verification command.

The raw selected legs and market metadata are preserved. Known exact game-winner series classify NFL/NBA/NCAAF/NCAAB; unrecognized series are unsupported. Missing times/descriptions stay null with gaps, while invalid identities, duplicate legs, and incomplete batches fail closed. Optional caller-supplied milestones join exact event tickers. Live market-only extraction does not fetch milestones or promote occurrence/close/expiration times into kickoff. Every leg declares pregame availability unverified; raw outcome/current-price fields are provenance, not model inputs.

## Required Kalshi analysis and historical replay (not implemented)

SportsIQ must analyze single-game and multileg Kalshi combinations, including mixed-league parlays across NFL, NBA, NCAAF, and NCAAB. A future read-only adapter may collect market/event metadata and price snapshots through documented market-data endpoints.[7] Keep a reviewable `(league, game provider ID) <-> (Kalshi event/market ID)` crosswalk, including team identity, scheduled start, exact proposition/settlement rules, as-of times, confidence and ambiguity flags. Preserve per-leg provenance and evaluate joint dependence; multiplying marginal probabilities without justified independence is not sufficient. Label hypothetical research combinations separately from provider-supported products; do not assume every cross-league combination is available. No authenticated API access, order methods, trade execution, Discord bot changes, or automatic market matching is approved here. Predictive analysis remains unimplemented; the report module currently formats discovery only.

Historical replay must use information available before each game's start, without outcome leakage. Each replay records a decision cutoff strictly before tipoff/kickoff, the start-time version known at that cutoff, and source availability/publication and retrieval timestamps. As-of joins must exclude later corrections, game outcomes, post-cutoff prices, future rankings, and season-end aggregates from inputs; final results are evaluation labels only. Training and validation must be chronological and restricted to information available at the decision cutoff. For an initial multileg/parlay decision, the common cutoff must precede the earliest leg's start; a later leg cannot use an earlier leg's outcome in that original decision. Any separately modeled later decision needs its own cutoff and cannot overwrite the original replay.

Point-in-time snapshots, market-price history, and feature/model provenance are future prerequisites. Current `retrieved_at` records local observation, not proof of earlier public availability, and the existing two-table schedule store is not a complete replay archive. Reject or label missing pregame evidence as a coverage gap instead of backfilling current/final data. Do not infer historical snapshot availability from a provider's historical game range.

## College data approval gate (documentation reviewed October 18, 2026)

BALLDONTLIE documents `GET /ncaaf/v1/games` and `GET /ncaab/v1/games`; both require ALL-STAR or GOAT, not the permanent free tier, and player/team statistics require GOAT.[14][15] Free accounts require a key and allow 5 requests/minute; a paid-tier trial is time-limited, not permanent free schedule entitlement.[14][15] NCAAF coverage is primarily FBS from 2004 with no non-FBS guarantee; NCAAB describes Division I from 2003.[14][15] Both use cursor pagination with 25 default/100 maximum; the README records free endpoint differences and query filters.[14][15] No college API requests, trials, subscriptions, college integrations, or dependencies are added here.

Evaluate authorized alternatives through SportsDataIO's College Football/College Basketball APIs and Sportradar's NCAAFB/NCAAMB B2B APIs.[16][17][18] Sportradar's NCAAMB reference describes authenticated schedule/game retrieval separately.[19] SportsDataIO permits storage/modeling under a suitably scoped commercial license, not a blanket grant for every feed/use case.[9] Selection requires explicit competition coverage, historical point-in-time evidence, cost/quota review, and written rights covering storage, analytics and outputs; no account entitlement or free production access is presumed. These are later-evaluation candidates only, not enabled sources.

## Known limitations and approval gates

The NBA fixture is synthetic, not a captured provider payload. BALLDONTLIE calls require account/key and tier entitlement; its terms restrict competing services and resale of raw data, and do not guarantee timeliness.[5] nflverse licenses and SportsDataIO rights remain separate decisions.[1][9] Schedule date filtering follows the documented `dates[]` parameter; the adjacent-date query is conservative but does not guarantee completeness if source game dates are wrong. Only the scoped Milestone 2C public market discovery is enabled; predictive analysis and historical ingestion remain out of scope.

## Sources

[1] https://github.com/nflverse
[2] https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html
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
[14] https://ncaaf.balldontlie.io
[15] https://ncaab.balldontlie.io
[16] https://sportsdata.io/developers/api-documentation/ncaa-football
[17] https://sportsdata.io/developers/api-documentation/ncaa-basketball
[18] https://developer.sportradar.com/football/docs/ncaafb-ig-api-basics
[19] https://developer.sportradar.com/basketball/docs/ncaamb-ig-api-basics
