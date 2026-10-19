# Milestone 2D: narrow NFL identity matching

Read-only identity matching, not predictions, trading, or historical replay.
The branch was created from main, then the completed 2C prerequisite was
cherry-picked as 39cd1d9 because main did not contain f9d95c4. Main is unchanged.
The clean prerequisite suite passed 74 tests before live extraction.

## Scope and matching contract

`sportsiq.matching.nfl.match_nfl_leg(leg, games, *, team_ids=None, source_games=None)` is pure/offline.
This initial allowlist covers ARI, LAR, SF, WAS and exact observed aliases,
including Los Angeles R, LA Rams, ARI Cardinals, WAS Commanders, SF 49ers,
and WSH. Other teams/templates are UNSUPPORTED pending explicit alias tests.
No fuzzy city/name-only lookup or guessed cross-provider UUID conversion occurs.
An optional canonical-team -> BALLDONTLIE string-ID crosswalk is checked against
both provider teams; conflicting known IDs or name/abbreviation fields reject
that candidate. All provider game/team IDs and the Kalshi football-team UUID,
event ticker, market ticker, side, proposition and source evidence are retained.
No static numeric provider IDs are invented or inferred from Kalshi UUIDs.

A recognized exact NFL winner-rule template must identify both teams, the YES
proposition, and an explicit original calendar date. The provider Eastern day
must corroborate that date; ticker dates are never a date source. This is an
explicit America/New_York calendar-date policy, not proof of the rule author's
timezone or kickoff. International/unclear calendar conventions require separate
verification. `vs` is unordered, never a home/away claim; explicit `at` must agree
with provider away/home. YES and NO are preserved literally; NO is NOT relabeled
as the opposing team (including possible tie/fair-price settlement semantics).

Outcomes: MATCHED for exactly one consistent pair/date/context candidate;
AMBIGUOUS for multiple candidates or a postponed/canceled/delayed/suspended/
abandoned/unknown lifecycle; NOT_FOUND for no consistent candidate in supplied
coverage, missing games, invalid dates, identity/date/scheduled-start conflicts;
UNSUPPORTED for non-NFL series, unrecognized rules or unresolved aliases.
Rescheduled dates are not silently shifted or matched within a guessed window.
Rejected provider-identity and date/time candidates retain their provider game/team
IDs, normalized schedule fields, source projection and rejection reason. Conflicting
or missing raw selection/market identities, raw rules versus flattened description,
and selection versus YES proposition are UNSUPPORTED, never MATCHED. Synthetic
fixtures use explicit, internally consistent raw identities too.

Provider start timestamps remain UTC, with offset-aware Eastern display.
Explicit milestone scheduled timestamps, if supplied, must equal the provider
schedule instant. A supplied raw milestone must identify the leg via its related
or primary event tickers. Its `start_date` must corroborate any flattened
`scheduled_start` as the same aware instant (equivalent offsets are accepted);
conflicting evidence is retained and never MATCHED. If flattening is absent/null,
the supplied raw start still constrains the match; invalid/naive raw starts fail
closed. Direct-service callers with `raw_milestone=None` may continue supplying
synthetic scheduled evidence without a raw milestone. Occurrence is never
kickoff or a matching instant: differences
are flagged. Neither current final-game schedule metadata nor this capture proves
actual historical kickoff or availability before a pregame cutoff. No scores,
results, settlement values or prices are read by the matching logic.

JSON evidence retains outcome-free, positive-allowlisted `raw_selection`,
`raw_market` (identities, rules, YES/NO subtitles, football-team custom strike and
source time fields), `raw_milestone`, extractor gaps and source timestamps on every
leg, including unsupported and conflicting legs. The optional `source_games`
mapping is keyed by BALLDONTLIE string game ID. The offline CLI supplies it from
the saved page. Candidate `source_record.date` preserves the original provider
date string exactly, including offset and precision, alongside normalized UTC/ET
fields. Direct Game-only callers instead receive `source_record: null` and an
explicit `source_evidence_gap`; raw source values are never reconstructed.
Unknown fields, prices, results and scores are not retained in source projections.

Malformed nested input shapes (including null market/custom strike and empty
timestamp objects) are rejected by the CLI with sanitized exit 2, without a
traceback. Duplicate provider game IDs, including identical repeated records,
are rejected before matching or building the raw-source mapping with the same
sanitized exit 2. Distinct IDs retain their own source records.
Absent/null optional timestamps remain absent; invalid scheduled-start
instants fail closed. Invalid or naive occurrence instants are explicitly unknown
in JSON uncertainty and unmatched/unsupported summaries, never interpreted in the
host timezone or labeled UTC. Occurrence still never establishes kickoff.

## Offline use

First produce existing extractor JSON using its explicit offline or live mode.
The matching consumer itself cannot perform network requests, read credentials,
open SQLite, or refresh schedules:

    .venv/bin/python -m sportsiq.matching --extraction /path/extracted.json --games /path/saved-nfl-games-page.json --format summary

`--format json` retains per-leg match evidence, candidates, uncertainty and missing
pregame inputs. Games input is a raw saved NFL Games page with `data` and `meta`;
coverage is always described as the supplied page only, not a complete historical
schedule. A remaining cursor is retained, never followed. Synthetic edge cases
are in `tests/fixtures/nfl_matching.json`. The observed field projection in
`tests/fixtures/nfl_combo_observed.json` retains all 12 selections and only the
two matching provider records, excludes scores/prices/results, and is explicitly
not a pregame snapshot. Its projection is not a complete provider response.

## Bounded validation of the supplied URL

Exact combo event: KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y
Exact selected market: KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y-RXGIQQ2OG

One no-retry 2C extractor workflow used exactly two public Kalshi GETs (combo
and exact-ticker batch); no additional Kalshi lookup. After the new offline
suite passed, one no-retry, single-page BALLDONTLIE NFL Games GET queried
October 17-21, 2026 (both rule dates and rollover neighbors). It returned 13
records with no continuation cursor. No paid endpoints, stats, odds, database
writes, orders or credential output. Capture retrieval instants are recorded in
the observed fixture and are not provider publication or pregame timestamps.
The committed per-leg report is `docs/nfl-combo-validation.txt`.

The supplied combo is mixed: 12 legs, all YES, 10 NCAAF and 2 NFL. All event and
market identities are preserved; no two-leg assumption was made. Both NFL
matches use provider home/away metadata, not the order of a `vs` rule:

- Leg 11, KXNFLGAME-26OCT18ARILAR / KXNFLGAME-26OCT18ARILAR-LAR:
  Los Angeles R YES, Arizona Cardinals at Los Angeles Rams, BALLDONTLIE 1392304.
  Current scheduled start 2026-10-18T20:05:00+00:00 / 16:05 EDT.
  Kalshi occurrence 2026-10-18T23:05:00+00:00 / 19:05 EDT, NOT kickoff.
- Leg 12, KXNFLGAME-26OCT19WASSF / KXNFLGAME-26OCT19WASSF-SF:
  San Francisco YES, Washington Commanders at San Francisco 49ers, 1392308.
  Current scheduled start 2026-10-20T00:15:00+00:00 / October 19, 20:15 EDT.
  Kalshi occurrence 2026-10-20T03:15:00+00:00 / October 19, 23:15 EDT, NOT kickoff.

The other 10 legs are UNSUPPORTED by this NFL-only matcher; college Games
access was not attempted. Both NFL occurrence/schedule differences are explicit
uncertainties, not silently corrected kickoff times. Missing pregame inputs for
all legs: verified historical kickoff, point-in-time schedule/cutoff,
injuries/rosters, team/player features, timestamped prices/rules and dependence
inputs. No probabilities, pick ratings, or outcome-based predictions are made.

## Verification

    .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

All tests run offline, including the observed projection regression, exact
pairs, aliases, known provider-ID conflicts, opponent/home-away restrictions,
Eastern/UTC rollover, ambiguous candidates, missing selections, postponements,
reschedules, source timestamp conflicts, unsupported leagues, NO semantics,
outcome-field isolation, and the offline JSON/summary CLI.
