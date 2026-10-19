# Milestone 2E-E: consolidated Kalshi parlay reporting

## Invocation and defaults

From the project root, with no network access:

    .venv/bin/python -m sportsiq parlay-report --url 'https://kalshi.com/markets/kxmvecrosscategory/combo/KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y?utm_source=kalshiapp_eventdetails&marketTicker=KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y-RXGIQQ2OG' --format json
    .venv/bin/python -m sportsiq parlay-report --url 'https://kalshi.com/markets/kxmvecrosscategory/combo/KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y?utm_source=kalshiapp_eventdetails&marketTicker=KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y-RXGIQQ2OG' --format summary

The equivalent standalone entry is `python -m sportsiq.parlay_report`. JSON is the default. Stdout contains only the requested report; malformed URLs, incomplete market inventories, malformed inputs and transport failures produce sanitized stderr and exit 2. Exit 0 means a report was produced, **not** that a betting selection or original combo replay is supported. Missing historical data is a reported evidence gap, not a fatal discovery failure.

Defaults:

- Market/schedule input: existing `tests/fixtures/nfl_combo_observed.json`, an observed field projection, not a pregame archive or fresh live retrieval. Its captured source observations are preserved separately: Kalshi `2026-10-19T00:10:00.405482+00:00`; saved provider page `2026-10-19T00:28:19.645783+00:00`.
- Historical input: existing local `data/snapshots/nfl/2026-10-19T053443Z/`; never downloaded or silently replaced. A checkout without that untracked bundle still reports all legs/mappings with INSUFFICIENT_DATA analysis.
- `--offline PATH` overrides market metadata. It accepts the saved projection wrapper or the existing extractor's raw `combo_market` / `underlying_markets` / optional `milestones` bundle. Saved raw fields are reprocessed through the original extractor/classifier rather than trusting saved flattened labels. Missing optional title/rule fields remain explicit gaps; a missing underlying record rejects the whole extraction rather than silently shortening it.
- `--games PATH` supplies a saved raw NFL Games page (or wrapper containing `games_page`). No schedules are fetched. If no page is available in custom offline input, the report declares empty supplied coverage and cannot uniquely match NFL games.
- `--snapshot PATH` chooses an existing local snapshot directory, but cannot authorize new content or bypass the pinned verifier.
- `--cutoff AWARE_TIMESTAMP` applies one common analysis cutoff to every leg. No cutoff is inferred from a ticker, market expiration or occurrence time.

Only explicit `--live` enables the existing `KalshiClient` and `fetch_parlay` workflow: at most two public GET attempts, no retries, fixed API origin, one combo lookup plus one exact underlying-market batch. `--live` and `--offline` are mutually exclusive. NFL schedules and historical statistics remain local even in live mode; no paid API, price history, trades, credentials or orders are accessed. Live mode was tested with an injected replay transport, **not executed against Kalshi during this milestone**. Other URLs need their own corresponding saved metadata or an explicit live request; the default fixture is not relabeled to match an arbitrary URL.

## Status and chronology contract

Each leg preserves exact event/market tickers and YES/NO side; NO is never translated into the opponent. It includes league/classification source, selection/title/rule text, raw source timestamps, existing matcher evidence and source projections, available metrics, lineage, missing evidence and warnings. Existing extractor classifications NFL/NBA/NCAAF/NCAAB are retained; its `unsupported` classifier value is displayed as `unknown` while retaining `extractor_league: unsupported`.

Two independent status layers:

| Layer | Values | Meaning |
| --- | --- | --- |
| `mapping.outcome` | MATCHED, AMBIGUOUS, NOT_FOUND, UNSUPPORTED | Existing NFL rule/pair/date/context identity mapping in supplied schedule coverage |
| `analysis.status` | SUPPORTED_EVIDENCE, INSUFFICIENT_DATA | Whether verified descriptive historical evidence is attached to this exact selection/context |
| `analysis.engine_assessment` / `combo_assessment` | INSUFFICIENT_DATA | No validated selection rating or joint model exists |

SUPPORTED_EVIDENCE means **descriptive data only**, not a supported bet, numerical confidence, probability, fair price, EV or recommendation. The historical adapter currently routes only the two reviewed exact YES markets. Other NFL markets/NO selections can still map but do not borrow a different selection's history. Non-NFL legs remain visible without requiring a statistical adapter.

The default consolidated report is an **independently timed per-leg review**, not a replay of the original combo before its earliest leg:

- Rams intended cutoff: `2026-10-18T19:00:00Z`.
- SF intended cutoff: `2026-10-19T23:00:00Z`; independently reviewed scheduled kickoff `2026-10-20T00:15:00Z` (October 19, 20:15 EDT). Actual kickoff remains unverified.
- Unsupported/unconfigured leg cutoffs remain null rather than invented from ticker dates.
- Root `analysis_cutoff` is null in this default mode because there is no common decision time. The explicit scope and warning prohibit backdating SF's later capture to earlier college/Rams legs. Root `original_combo_replay_supported` is false and `combo_assessment` remains INSUFFICIENT_DATA.

For a common-cutoff check, add `--cutoff 2026-10-16T12:00:00Z`. The October 19 snapshot then fails both NFL cutoff gates, with zero attached metrics. This is a diagnostic example, not a verified original entry time. Current/saved market identity and mapping metadata are kept for discovery, never treated as independently verified pre-cutoff market information or statistical features.

## Reuse and evidence gates

The implementation calls the existing `extract_parlay` / `fetch_parlay`, classifier, pure BALLDONTLIE normalization, `match_nfl_leg` and `assess_snapshot`/shared assessment engine. No provider client, historical parser, source approval registry or cutoff-validation algorithm is duplicated. Exact source hashes, licensing evidence, publication/capture chronology, terminal status, target exclusion and reviewed inventories remain the existing verifier's responsibility.

A successful source verification is insufficient to attach it to an arbitrary matched market: consolidation additionally compares the exact market/side, canonical proposition/team pair and normalized schedule instant against the accepted assessment context. Conflicts remain MATCHED at the mapping layer if that is what the supplied metadata says, but produce INSUFFICIENT_DATA analysis with no attached statistics. Caller-supplied source flags cannot turn on historical evidence. Malformed/missing/tampered snapshot metadata fails closed.

Report provenance records local input URI/hash, distinct declared saved observations, zero-or-bounded current-run HTTP count, snapshot reference and verified source/record lineage. Report generation uses the current UTC clock, never the old capture timestamp. Declared saved metadata observations are labeled as such; fixture hashes are reproducibility receipts, not proof of historical publication. Existing matcher allowlists strip raw outcomes, prices and unknown source fields. Text rendering JSON-escapes external display values. The command writes no files, opens no database and loads no credentials; callers can capture stdout. There is no Telegram implementation, configuration change or messaging side effect. A future integration can parse the stable JSON/exit status and chunk or attach the text report.

## Verified supplied combo

Actual offline CLI execution regenerated the following paired artifacts from the same structured result:

- `docs/consolidated-parlay-report.json`
- `docs/consolidated-parlay-report.txt`

All **12 exact selected legs** are retained: ten NCAAF and two NFL, all YES. NFL mappings:

- Rams YES, `KXNFLGAME-26OCT18ARILAR-LAR`: MATCHED to BALLDONTLIE `1392304`, Arizona at LA, scheduled `2026-10-18T20:05:00+00:00`. Analysis INSUFFICIENT_DATA: the October 19 capture is after the Rams cutoff; no historical metrics are substituted.
- SF YES, `KXNFLGAME-26OCT19WASSF-SF`: MATCHED to `1392308`, Washington at SF, scheduled `2026-10-20T00:15:00+00:00`. Analysis SUPPORTED_EVIDENCE for ten verified prior records, five per team, using the existing CC BY 4.0 non-FTN nflverse PBP capture. Engine assessment remains INSUFFICIENT_DATA. SF W–L–T 5–0–0, points 154–93; Washington 1–3–1, points 115–149. Home/away/neutral splits and observed-complete-by-capture provenance are retained; no exact final-whistle times are invented.

The ten college legs are UNSUPPORTED mappings with INSUFFICIENT_DATA analysis and explicit adapter gaps. No college games, kickoffs, injuries or statistics are inferred. All leagues' missing predictive methods, injuries/rosters, price evidence and cross-leg dependence remain visible. Independent full-season/opponent-history completeness and target actual kickoff are still unverified.

## Verification and repository scope

Baseline main was `5b66348503a47ce182fda5f7255ed026aab95bbe`, with all 180 tests passing and no tracked changes. The user explicitly authorized leaving pre-existing untracked `data/` artifacts untouched/unstaged. `feature/consolidated-parlay-report` did not exist and was created from that main state.

All **202 offline tests pass: 180 existing plus 22 new integration tests**. Tests cover the mixed twelve-leg combo; all five classification buckets; optional/missing metadata; strict inventory and provider-ID failures; MATCHED/AMBIGUOUS/NOT_FOUND/UNSUPPORTED separation; source-date/context conflicts; missing, malformed and tampered snapshots; common-cutoff leakage refusal; literal NO sides; portable synthetic verified bundles; deterministic fixed-clock JSON/text; escaped text; discarded outcomes/prices; default offline network/database/credential isolation; sanitized CLI errors; raw-bundle input; and explicit live routing through the actual existing two-GET client with an injected transport. No dependency installation was needed.

Actual JSON and text CLI executions agreed except their separately generated report times; the committed text was rendered from the committed JSON for exact pairing. All 14 manifest-listed original snapshot files were rehashed unchanged. Security/whitespace checks and one focused independent staged-diff review gate the local commit. No Docker, n8n, Hermes, credential, Discord-bot, trading-service, database, price-history, merge or push changes are part of this milestone.
