# Kalshi parlay extraction (Milestone 2C)

This is read-only discovery, not prediction, historical replay, or trading.
Existing schedule providers, the NFL/NBA schedule `League` enum, and SQLite are
unchanged. No credentials, database, bot, or background services are involved.

## Offline example

The committed fixture is synthetic, includes YES and NO, and is NOT a capture
of the historical 46-leg combo. Quote URLs so the shell preserves `&`.

    .venv/bin/python -m sportsiq kalshi-parlay --url 'https://kalshi.com/markets/kxmvecrosscategory/synthetic/KXMVECROSSCATEGORY-SYNTHETIC?marketTicker=KXMVECROSSCATEGORY-SYNTHETIC-EXAMPLE' --offline tests/fixtures/kalshi_parlay.json --format summary

Use `--format json` (the default) for structured output, including original
combo, leg selection, underlying market, and optional matched milestone metadata.
Nothing is automatically persisted. `observed_at` is the time this extraction
was performed, even offline; it is NOT the original capture/publication time.
Any original timestamps remain in the raw metadata. Offline output is never
represented as a verified historical snapshot.

## Explicit live discovery

`--offline FIXTURE` and `--live` are mutually exclusive and one is required.
For the reference combo, a bounded manual verification is:

    .venv/bin/python -m sportsiq kalshi-parlay --url 'https://kalshi.com/markets/kxmvecrosscategory/akron-vs-miami-oh/KXMVECROSSCATEGORY-S20267BTSDQSEL5EKTK7Z?utm_source=kalshiapp_eventdetails&marketTicker=KXMVECROSSCATEGORY-S20267BTSDQSEL5EKTK7Z-WLVISUWDL' --live --no-retries --format summary

This is one verification workflow with at most TWO HTTP attempts: one selected
combo GET, then one batch GET containing exactly its underlying tickers. Stop
on failure; do not rerun during a capped verification. No event-by-event fanout,
price history, milestone fetch, or alternate-host fallback is performed.

The default public origin is `https://external-api.kalshi.com/trade-api/v2`.
The only paths are `GET /markets/{ticker}` and `GET /markets?tickers=...&limit=100`.
Both are documented public market-data operations.[1][2] There is no account
login, Authorization header, order operation, or credential loader. Redirects
are disabled. Network errors and 429/5xx responses get at most two retries per
operation (six total HTTP attempts per client/extraction), with a 10-second
socket timeout (configurable programmatically up to 30 seconds) and retry sleeps
bounded to five seconds. Excessive Retry-After aborts instead of retrying early.
`--no-retries` caps the entire workflow at two attempts. Responses and offline
fixtures are capped at 2 MiB; combinations at 100 legs. Oversized, incomplete,
duplicate, unexpected, or paginated underlying batches fail closed. Missing or
invalid mandatory identities/sides abort; missing descriptive/time metadata
remains null with explicit gaps. JSON errors are sanitized; nonfinite numbers
are rejected. No new dependencies are required.

## Reusable interfaces and fixture contract

- `parse_kalshi_url(url)` returns a `KalshiLink`. Only exact HTTPS Kalshi market
  URLs on `kalshi.com` or `www.kalshi.com` are accepted. Credentials, ports,
  fragments, controls, malformed identifiers and missing/duplicate/empty
  `marketTicker` values fail. The original URL and selected identifier are
  preserved; the slug never supplies the selected market.
- `KalshiClient` accepts an injected transport and sleeper for offline tests.
  `market(ticker)` and `markets(tickers)` validate exact returned identities.
- `fetch_parlay(link, client)` fetches the selected combo and underlying records.
- `extract_parlay(link, bundle, source="offline")` extracts without network or
  storage. `dataclasses.asdict(result)` is JSON-serializable. Raw records are
  deep-copied so caller mutation cannot silently alter the output.
- `parlay_summary(result)` renders each leg with terminal-escaped provider text.

Fixture JSON is an object containing:

    combo_market: selected API market object, including mve_selected_legs
    underlying_markets: array of exact underlying API market objects
    milestones: optional array of caller-supplied milestone objects

See `tests/fixtures/kalshi_parlay.json`. The selected combo must match the URL's
market AND event. Each leg requires `event_ticker`, `market_ticker`, and lowercase
`side` equal to `yes` or `no`. API selection order is retained. Duplicate markets,
including contradictory YES/NO selections on the same market, are rejected,
not silently deduplicated. Optional milestones join only by exact
`related_event_tickers` / `primary_event_tickers`; ambiguity aborts.

Classification uses an explicit, conservative game-winner series allowlist:
`KXNFLGAME` -> NFL, `KXNBAGAME` -> NBA, `KXNCAAFGAME` -> NCAAF,
`KXNCAABGAME` -> NCAAB. Other series, including unrecognized proposition series,
are `unsupported`, not classified from titles, team abbreviations, or resemblance.
This does not establish division, gender, BALLDONTLIE IDs, or data entitlement.
Schedule adapters remain NFL/NBA only.

`selection` preserves the provider's side-specific subtitle; `side`, `title`,
and `description` preserve the actual proposition context. NO means the negative
of that proposition, NOT an inferred opposing-team selection. Provider NO and
YES subtitles can be identical; do not interpret the label alone.

## Time and historical safety

Every reported time has its original value and a source-field label:

- `scheduled_start`: optional matched milestone `start_date`.
- `occurrence`: market `occurrence_datetime`; NEVER promoted to kickoff.
- `market_updated`: market `updated_time`.
- `schedule_updated`: optional milestone `last_updated_ts`.
- `actual_start`: only an explicitly supplied milestone `actual_start_time`.
  This is an optional caller-supplied extension, not a guaranteed Kalshi field.
  In its absence actual start remains unknown.

Naive/malformed timestamps remain raw, but their interpreted values are null
with gaps. Missing fields remain null; differing scheduled/occurrence instants
are flagged. Market close/expiration, milestone end time, lifecycle status,
ticker dates and settlement timestamps NEVER become game-start times. Live
market-only discovery intentionally leaves scheduled/actual starts unknown;
a separate verified schedule/milestone acquisition scope is needed to fill them.

Original API metadata can contain outcomes, settlement values, or current
prices. These are preserved for provenance, NOT used as prediction inputs.
Every leg is marked `pregame_availability_unverified`, regardless of how plausible
its dates appear. No historical price coverage, pregame availability, replay
readiness, probability, confidence grade, recommendation, or cross-provider
match is inferred. The historical reference is an extraction regression target,
not a predictive backtest.

## Verification

    .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

All tests are offline. They cover strict URLs, malformed/incomplete metadata,
YES/NO, four supported series and unknowns, timestamp provenance, duplicate legs,
46-leg ordering, bounded GET/retry/byte budgets, sanitized failures, and CLI
isolation from credentials/storage. No live requests run in the test suite.

## Official API references

[1] https://docs.kalshi.com/api-reference/market/get-market
[2] https://docs.kalshi.com/api-reference/market/get-markets
