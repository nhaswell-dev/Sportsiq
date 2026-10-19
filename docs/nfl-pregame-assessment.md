# Milestone 2E-B: offline NFL descriptive assessment

This implements a pure, fixture-first evidence gate and per-leg history report, not a prediction engine. All committed example statistics, teams, market identifiers, source assertions, and kickoff observations are **synthetic**. They are not actual NFL statistics or captures of the Rams/49ers selections.

## Run from the project root

    .venv/bin/python -m sportsiq.analysis --fixture tests/fixtures/nfl_assessment_synthetic.json --format json
    .venv/bin/python -m sportsiq.analysis --fixture tests/fixtures/nfl_assessment_synthetic.json --format summary

JSON is the default. This standalone module CLI deliberately leaves every existing SportsIQ command unchanged. There is no live flag, network client, credential loader, database, output-file write, or external source lookup. Source references are inert strings; the service never opens them. Output goes to stdout. Exit 0 means a well-formed fixture produced a report, **not** that a selection is supported. Malformed input/file errors exit 2 with a sanitized message. Inputs are limited to 2 MiB, 100 legs, 100 source snapshots, and 10,000 records per snapshot. Duplicate JSON keys, nonfinite numbers, unknown top-level fields, and malformed leg identities fail closed.

Service: `sportsiq.analysis.nfl.assess_nfl(payload)` returns a JSON-compatible dictionary without modifying the input. Renderer: `sportsiq.reports.nfl_assessment.assessment_summary(result)` escapes external terminal control characters.

## Output and assessment policy

Each leg reports its exact opaque market/game/selection IDs, one explicit shared analysis cutoff, scheduled and separately verified actual kickoff, source IDs, available/missing metrics, supporting/opposing historical comparisons, missing data, and uncertainty. The example has two independent leg reports; it is not a supported combo product or a joint-probability assessment.

Every selection assessment in 2E-B is `INSUFFICIENT_DATA`, even when descriptive metrics are available. There is no validated predictive method, full-season coverage certificate, or calibrated selection recommendation. Metric availability is separate: `AVAILABLE`, `PARTIAL`, or `MISSING`. Available means eligible **within the supplied fixture evidence**, not independently authenticated real-world data. A comparison may favor the selection's historical scoring while the selection assessment remains insufficient. There are no numerical winning probabilities, expected values, Supported/Avoid ratings, or trade actions.

All results explicitly say whether the fixture is `synthetic` or `observed`. Synthetic outputs display `SYNTHETIC DATA - NOT ACTUAL NFL STATISTICS`. Observed inputs still carry the warning that external provenance is not independently authenticated. Merely changing `data_kind` does not authorize a source: source labels must agree and observed evidence cannot use the synthetic availability-proof type or synthetic reference markers.

## Exact fixture contract (schema version 1)

The committed JSON example is the executable schema example; no nflverse, BALLDONTLIE, or Kalshi payload format is implicitly accepted.

Top-level keys are exactly:

- `schema_version`: integer 1 (not a boolean).
- `data_kind`: `synthetic` or `observed`.
- `mode`: `historical` or `prospective`; this is an explicit fixture mode, not inferred from the machine clock.
- `analysis_cutoff`: timezone-aware ISO 8601 instant, normalized to UTC in output. Every leg uses this same cutoff; a separate later decision requires a separate fixture/report.
- `teams`: explicit string team-ID to display-name mapping. No fuzzy alias or cross-provider ID conversion.
- `legs`: nonempty array of objects containing exactly `leg_id`, `market_ticker`, `side`, `selected_team_id`, `game_id`, all nonblank strings. Leg IDs, target game IDs, and market tickers are unique. Initially only literal lowercase `yes` for the selected team's game-winner proposition is assessable; NO is retained but never relabeled as the opposing team. Selected team must be in the target schedule pair. Tickers are opaque identifiers, not evidence of dates, rules, or team identity.
- `sources`: snapshot envelopes described below. Empty sources are valid input and produce insufficient evidence, not fabricated metrics.

Each source envelope contains exactly:

- `source_id`, `data_kind`, `provider`, `reference`, `version`: explicit nonblank identity/version metadata; source data kind agrees with the fixture.
- `reliable`: literal true, plus nonblank `reliability_evidence`.
- `license`: exactly `status`, `reference`, `allowed_uses`, `attribution`; status must be `approved`, references/attribution nonblank, and allowed uses include both `analysis` and `display`.
- `published_at`, `revision_at`, `available_at`, `retrieved_at`: aware timestamps, with publication <= revision <= availability <= proof observation <= retrieval. They are not interchangeable.
- `availability_evidence`: exactly `kind`, `reference`, `observed_at`. Synthetic fixtures use kind `synthetic`. Observed fixtures require `archive` or `capture`. `capture` observation must equal retrieval; a later local retrieval does not prove an earlier capture. An `archive` observation may predate local retrieval, subject to external review of the referenced archive.
- `records`: typed observations below.
- `content_sha256`: SHA-256 of `json.dumps(records, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()` (default ASCII escaping and UTF-8 bytes). It binds the provided records to the fixture snapshot; it does not prove that a remote archive contained those records or that an attestation is truthful. Modify a fixture snapshot deliberately and recompute its hash; never backdate a real source correction.

**Trust boundary:** license approval, reliability and archive evidence are caller-supplied attestations checked for schema, consistency, time and content binding. They are not a remote signature, legal determination, independent review, or proof of complete NFL coverage. Source text does not configure or execute anything. Real sources require external approval and archive verification before entering a fixture. No data provider is automatically whitelisted, and HTTP accessibility would not confer permission. The synthetic example's approval covers only its original synthetic test data.

## Observation types and leakage gates

Only these record types are recognized. Unknown record kinds/fields, malformed records, and unsupported season types are excluded without echoing their values. Exclusions contain locally generated reasons, source IDs, and (for ambiguous accepted identities) kind/game IDs, never raw results or price payloads. Invalid source envelopes exclude their records and preserve only a source ID/reason, not arbitrary metadata. Duplicate source IDs quarantine all copies. Duplicate eligible `(kind, game_id)` records quarantine all copies, even if identical or in different sources; no implicit latest-version selection.

### scheduled_game

Exactly `kind`, `game_id`, `season`, `season_type`, `home_team_id`, `away_team_id`, `neutral_site`, `scheduled_kickoff`. Teams are distinct known IDs, season is an integer, season type is `REG`, neutral-site is a boolean, kickoff is aware. A target schedule must be unique and source-eligible before cutoff. It is not inferred from a market occurrence or settlement time.

### game_result

The same identity/season/venue fields, plus exactly `started_at`, `completed_at`, `status`, `home_points`, `away_points` (no scheduled-kickoff field). Status must be `final`; points must be nonnegative integers <= 200, never booleans. Times must satisfy start < completion < cutoff and completion <= source revision. Snapshot publication, revision, availability, and proof observation must all be **strictly before** cutoff. Retrieval may be later only with eligible archive/synthetic evidence; present-day correction timestamps do not pass.

All target game results for **every** leg are excluded from the complete history universe, including opponent-strength calculations, even if a fixture falsely backdates the result. Only the target's REG season is aggregated. Results after cutoff, at cutoff, live games, invalid scores, prior-game duplicates, unsupported statistics/ratings/roster updates/prices, and source revisions without pre-cutoff availability cannot become features. A post-cutoff revised duplicate cannot replace an independently eligible earlier snapshot.

### kickoff_verification

Exactly `kind`, `game_id`, `actual_kickoff`. An aware actual kickoff requires otherwise valid, reliable, approved, hash-bound source provenance with revision at/after the event. It can be published after cutoff **only to verify chronology**, never as a feature source. Output retains its separate source IDs and `feature_eligible: false` when appropriate. Postgame scores, lineups, injuries and ratings have no place in this record type.

A historical report requires actual-kickoff evidence; missing or ambiguous evidence withholds metrics. Cutoff must strictly precede both scheduled and verified actual kickoff; equality is rejected. A prospective report may use a unique eligible schedule without actual kickoff, but explicitly records `actual_kickoff_unverified`; it never asserts a settled result. Known contradictory actual kickoffs block prospective metrics too. Prospective mode is not a way to disregard a verified earlier kickoff. The program uses no current-time default and makes no live game-status claim.

## Metric definitions

All metrics describe **supplied validated games only**, never an asserted complete season record. Each includes status, selected/opponent values, source IDs and exact contributing game IDs. Without eligible team history, values are null rather than invented zero-game statistics.

- `record`: wins, losses, ties, games; historical `win_fraction = (wins + ties / 2) / games`, null with no games. This fraction is **not** a prediction of the target game's winning probability.
- `home_away`: the same counts split into designated home, away and neutral. Neutral games are never counted as home-field evidence; a zero-sample split has zero observed counts and null fraction.
- `points`: prior total points scored/allowed and per-game averages; these are scoreboard points, not offensive EPA or a separation of offensive/defensive/special-team scoring.
- `opponent_strength`: equal-weight mean of unique previously faced opponents' historical win fractions, excluding each opponent's head-to-head games against the team being assessed. Uses only the same eligible source/game universe. Output includes each opponent record, number observed/total, and missing opponent IDs. Zero-game opponents are omitted, not rated as weak. Missing required comparisons are `MISSING`; a computed mean with omitted opponents is `PARTIAL` and adds a missing-data reason. This is not a full-season SOS, end-of-season ranking, or fitted opponent adjustment.

Comparisons in evidence-for/evidence-against use only historical record fraction (higher), points/game scored (higher), and points/game allowed (lower), when both teams have observations. These are unweighted descriptive differences, not validated causal or predictive criteria. Ties produce no directional claim. Venue splits and opponent-strength remain contextual metrics rather than an unsupported claim of home advantage or calibrated adjustment. Small samples, unverified complete coverage, rejected inputs and unsupported injuries/rosters/ratings/prices remain explicit limitations.

## Executed synthetic sample (abbreviated)

From the committed example, the readable command produces:

    SYNTHETIC DATA - NOT ACTUAL NFL STATISTICS
    Analysis cutoff: 2026-10-18T19:00:00+00:00
    synthetic-leg: Synthetic Harbor yes | INSUFFICIENT_DATA
      record [AVAILABLE] | source=history
        selected: 1 win, 1 loss, 0 ties; 2 supplied prior games
      points [AVAILABLE] | source=history
        selected: scored=42, allowed=35; per-game=21.0 scored / 17.5 allowed
      opponent_strength [AVAILABLE] | source=history
        selected: mean_opponent_win_fraction=0.5; 2 of 2 opponents observed
      Evidence for: higher observed scoring and lower observed points allowed
      Evidence against: none identified
      Missing: predictive_method_unvalidated; full_season_coverage_unverified

The fixture also produces a Synthetic Birch leg with 2 wins/1 loss in 3 supplied prior games. This excerpt abbreviates JSON dictionaries/wording; run the CLI for exact full JSON or the full readable output. None of these values describe actual teams.

## Verification and remaining real-selection gates

    .venv/bin/python -m unittest discover -s tests -p 'test_*.py'

Baseline: all 104 existing tests passed on the committed 2E-A branch with clean Git status. The new tests cover provenance/license/content integrity, strict cutoff and revision gates, excluded target/future information, source/record ambiguity, scheduled versus actual kickoff, prospective ambiguity, naive timestamps, UTC offsets, ties, neutral venues, missing/partial opponent records, report generation, strict JSON and size limits, terminal safety, input immutability, and no network/database/credential access. Original tests are unchanged.

Final verification: **131 offline tests passed (104 existing + 27 new)**, including an out-of-range UTC conversion regression identified during independent review. The actual module CLI was exercised in JSON and readable modes against the two-leg synthetic fixture. Staged whitespace and added-line secrets/security checks passed. No external data was fetched for this implementation.

For the real Rams YES / Cardinals and 49ers YES / Commanders selections, this milestone supplies no actual statistics and does not refresh the 2E-A research. Still needed:

1. Approved reusable historical datasets and verified pre-cutoff snapshot/publication evidence; nfldata licensing and immutable history gaps from `docs/nfl-pregame-data-audit.md` are not resolved by a fixture's `approved` string.
2. Exact 2D identity/rule mapping represented in the new fixture contract, approved point-in-time target schedule versions and an externally verified actual kickoff for every claimed historical report. At 2E-A audit time the 49ers game was upcoming; this offline milestone does not establish its later status or actual start.
3. Validated prior completed games for both teams and league-wide opponent histories; independent full-season coverage/reconciliation, excluded/missing-data review, and no post-cutoff corrections.
4. Separately licensed, timestamped injury/roster evidence if those features are later scoped. They remain unsupported here.
5. Written applicable Kalshi permission before any historical-price collection or modeling; no Kalshi price endpoint was called here. Timestamped entries, fees, settlement semantics, execution assumptions and all-leg cutoff/dependence evidence are required before any price-based or combo assessment.
6. A separately approved and validated predictive method/evaluation before probabilities, EV or selection ratings. None is implemented by 2E-B.

No dependencies installed, secrets used, live research performed, trading/orders, Docker/n8n/Hermes changes, merges or pushes. Existing analysis package marker and existing commands remain unchanged; the new submodule is additive.
