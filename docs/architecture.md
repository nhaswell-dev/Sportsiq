# SportsIQ architecture (Milestone 1.6)

## Current execution boundary

Only `sportsiq schedule --league nfl|nba --date YYYY-MM-DD --fixture PATH` is executable. It reads local synthetic JSON, filters by UTC start date, and prints normalized JSON; no HTTP transport, API keys, downloaded datasets, storage writes, or market/trading actions exist. The original CLI invocation with no `--league` remains NFL. The ESPN-shaped NFL source is fixture-only because automated extraction from ESPN is restricted without permission; public reachability is not authorization or a stable contract.[6]

## Shared domain

`Game` has a `League` (`nfl`/`nba`), `GameStatus`, timezone-aware `start_time`, home/away `Team` values, and string-valued provider-ID maps. `Team` supports an optional abbreviation. Both fixture parsers convert aware starts to UTC and use `unknown` status when the fixture has no recognized lifecycle state. The NFL parser gives recognized specific status names (including postponed and canceled) precedence over broad pre/in/post states; unfamiliar names stay unknown rather than being mislabeled. The legacy four-positional-argument `Game` constructor defaults to NFL and unknown status; all new adapters must pass the league explicitly. The CLI's `--date` means UTC calendar day, not the provider's local game date. A future provider must not guess a missing NBA tipoff timestamp or treat a naive timestamp as local time.

Use `(league, provider, provider_id)` as a source-scoped identity; do not join ESPN, BALLDONTLIE, nflverse, and Kalshi records just because names or dates resemble each other. Crosswalks should have review state, evidence, and versioned validity periods. Preserve both observed source timestamps and ingestion timestamps when persistence is introduced.

## Provider contracts and proposed stages

- `ScheduleProvider.games_on(day)` returns normalized `Game` records. Source protocols keep fixture parsing independent of HTTP. `ESPNNFLScheduleProvider` reads only injected local ESPN-shaped fixtures. `NBAFixtureScheduleProvider` reads only injected local BALLDONTLIE-shaped fixtures. Neither represents a licensed live NBA/NFL feed.
- NFL historical candidate: nflverse release snapshots with dataset-specific attribution/license metadata. Its published update schedule does not guarantee that any given asset is complete or fresh; the FTN share-alike exception needs review before use.[1][2]
- NFL and NBA current-schedule candidates: separate BALLDONTLIE read-only Games clients, only after an account/key is separately approved. The NBA Games endpoint is distinct from the NFL endpoint, and both free tiers allow Games but require keys and limit requests to 5/minute.[4][8] A later client must handle cursors, quotas/429, errors, schedule-date semantics, provenance, and source IDs. Paid player-stat endpoints are not implied by free game access.[4][8]
- NBA historical research is a separate licensing choice: BALLDONTLIE offers an API-wide history claim but no guarantee of complete old box scores or player stats; historical player stats need a paid tier.[8] SportsDataIO offers NBA feeds and a historical Vault under a use-case-specific license; actual NBA years/fields, pricing, storage, model training and report rights require confirmation before selection.[9][10][11]

## Future market matching, not implemented

A separate read-only Kalshi adapter could collect market/event metadata and price snapshots from its documented public endpoints.[7] Keep a reviewable `(league, game provider ID) <-> (Kalshi event/market ID)` crosswalk, including team identity, scheduled start, exact proposition/settlement rules, as-of times, confidence and ambiguity flags. Never infer a bet recommendation from a name match or a stale quote. No authenticated API access, order methods, trade execution or automatic market matching is approved here. Storage, analysis and report modules remain placeholders.

## Known limitations and approval gates

The NBA fixture is synthetic, not a captured provider payload; response schema and exact date behavior have not been validated against a live API. BALLDONTLIE calls need a separately approved account/key and tier entitlement. Its terms restrict competing services and resale of raw data, and do not guarantee timeliness.[5] nflverse release licenses and upstream rights vary by dataset, particularly FTN; SportsDataIO rights depend on a negotiated product/use-case license.[1][9] No live data freshness, actual season coverage, or historical asset completeness was tested. Do not connect data sources, scrape NBA.com/ESPN, or begin market integration without a separate milestone and permission.

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
