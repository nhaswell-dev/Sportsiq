# SportsIQ architecture (Milestone 2A)

## Current execution boundary

The default `sportsiq schedule --league nfl|nba --date YYYY-MM-DD --fixture PATH` reads local synthetic JSON. Explicit `--provider balldontlie` instead reads the project `.env` key and uses the official BALLDONTLIE Games endpoint for that league; it rejects `--fixture`. Both return normalized JSON for the requested UTC day. The NFL default and all existing fixture commands remain unchanged. There are no storage writes, market/trading actions, or live ESPN requests.[6]

## Shared domain

`Game` has a `League` (`nfl`/`nba`), `GameStatus`, timezone-aware `start_time`, home/away `Team` values, and string-valued provider-ID maps. `Team` supports an optional abbreviation. Both fixture parsers convert aware starts to UTC and use `unknown` status when the fixture has no recognized lifecycle state. The NFL parser gives recognized specific status names (including postponed and canceled) precedence over broad pre/in/post states; unfamiliar names stay unknown rather than being mislabeled. The legacy four-positional-argument `Game` constructor defaults to NFL and unknown status; all new adapters must pass the league explicitly. The CLI's `--date` means UTC calendar day, not the provider's local game date. A future provider must not guess a missing NBA tipoff timestamp or treat a naive timestamp as local time.

Use `(league, provider, provider_id)` as a source-scoped identity; do not join ESPN, BALLDONTLIE, nflverse, and Kalshi records just because names or dates resemble each other. Crosswalks should have review state, evidence, and versioned validity periods. Preserve both observed source timestamps and ingestion timestamps when persistence is introduced.

## Provider contracts and proposed stages

- `ScheduleProvider.games_on(day)` returns normalized `Game` records. Source protocols keep fixture parsing independent of HTTP. `ESPNNFLScheduleProvider` and `NBAFixtureScheduleProvider` remain offline. `BALLDONTLIEGamesProvider` selects the NFL or NBA Games endpoint through an injected `GamesClient`, normalizes IDs, lifecycle, teams and aware UTC starts, and rejects malformed records.
- NFL historical candidate: nflverse release snapshots with dataset-specific attribution/license metadata. Its published update schedule does not guarantee that any given asset is complete or fresh; the FTN share-alike exception needs review before use.[1][2]
- BALLDONTLIE Games client: constant HTTPS host and NFL/NBA paths; disabled redirects; project-local `.env` key only in Authorization; sanitized failures. UTC date queries cover adjacent provider dates and filter normalized UTC times; `per_page=100`, cursor cycle detection and ID deduplication cover pagination. Default timeout is 10 seconds, with a process-local 12.1-second request interval and at most two 429/5xx retries honoring Retry-After up to 60 seconds. Separate processes and other users of the key are not coordinated, so do not run concurrent quota consumers. The free tier allows Games, not paid stats.[4][8]
- NBA historical research is a separate licensing choice: BALLDONTLIE offers an API-wide history claim but no guarantee of complete old box scores or player stats; historical player stats need a paid tier.[8] SportsDataIO offers NBA feeds and a historical Vault under a use-case-specific license; actual NBA years/fields, pricing, storage, model training and report rights require confirmation before selection.[9][10][11]

## Future market matching, not implemented

A separate read-only Kalshi adapter could collect market/event metadata and price snapshots from its documented public endpoints.[7] Keep a reviewable `(league, game provider ID) <-> (Kalshi event/market ID)` crosswalk, including team identity, scheduled start, exact proposition/settlement rules, as-of times, confidence and ambiguity flags. Never infer a bet recommendation from a name match or a stale quote. No authenticated API access, order methods, trade execution or automatic market matching is approved here. Storage, analysis and report modules remain placeholders.

## Known limitations and approval gates

The NBA fixture is synthetic, not a captured provider payload. BALLDONTLIE calls require account/key and tier entitlement; its terms restrict competing services and resale of raw data, and do not guarantee timeliness.[5] nflverse licenses and SportsDataIO rights remain separate decisions.[1][9] Schedule date filtering follows the documented `dates[]` parameter; the adjacent-date query is conservative but does not guarantee completeness if source game dates are wrong. No market integration or historical ingestion is authorized.

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
