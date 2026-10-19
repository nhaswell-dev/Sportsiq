# Milestone 2E-D: verified observed-complete NFL snapshots

## Scope and result

The shared assessment engine now accepts a separately typed, evidence-bound prior result whose completion was **observed by a verified snapshot capture**, without pretending to know the final-whistle timestamp. Ordinary fixture/CSV validation remains strict and unchanged by default. This is descriptive analysis, not a probability, EV or trading recommendation.

Baseline: `main` at `1bf907fd35eac5c2fd8f00ba9caa3f7ff8935173`; all 155 existing tests passed. The only pre-existing untracked files were the expected 15 snapshot files and five earlier diagnostic artifacts under `data/`. Their complete inventory and all 14 manifest-listed file hashes were checked before creating `feature/nfl-observed-completion` from that tested state. No unexpected changes were found.

Actual execution now accepts ten prior SF/WAS game records from the existing real snapshot, five per team. It refuses to use that capture for the Rams' earlier pregame cutoff. The snapshot itself is not modified, downloaded again, executed as code, or committed as a large data blob.

## Exact offline commands

From the project root:

    .venv/bin/python -m sportsiq.analysis.snapshot --snapshot data/snapshots/nfl/2026-10-19T053443Z --selection 49ers --cutoff 2026-10-19T23:00:00Z --format json
    .venv/bin/python -m sportsiq.analysis.snapshot --snapshot data/snapshots/nfl/2026-10-19T053443Z --selection 49ers --cutoff 2026-10-19T23:00:00Z --format summary
    .venv/bin/python -m sportsiq.analysis.snapshot --snapshot data/snapshots/nfl/2026-10-19T053443Z --selection rams --cutoff 2026-10-18T19:00:00Z --format json

`--snapshot` and an aware `--cutoff` are required; selection defaults to `49ers`; JSON is the default. Exit 0 means a report, including a blocked report, was produced. Malformed request arguments exit 2. There is no live flag, approval flag, credential loader, database access, network transport, registry-file argument or automatic output-file write. The CLI writes stdout and includes its actual UTC report-generation time.

Public entry: `sportsiq.providers.nfl_snapshot.assess_snapshot(directory, *, cutoff, selection='49ers')`. The legacy `sportsiq.analysis.history` CSV path remains synthetic-only. Do not rename real data to synthetic or invent scheduled prior-game times to fit that older schema.

## What is approved

The code-owned `APPROVED_SNAPSHOTS` registry contains one production entry: the reviewed nflverse PBP 2026 capture.

- Original raw SHA-256: `d453d38c8d50086b9e2ce3dbb798d1bf57f981a9dd58025b4cf2c0a4ff15e9ee`.
- Snapshot manifest SHA-256: `5f4499d065c659bbf674ef5a3595f87eb3d9d5deac6ba8c9f95b6450ff4493df`.
- Capture completed: `2026-10-19T05:34:44.001488+00:00`.
- Publisher asset ID: `655240352`; asset created/updated: `2026-10-19T04:32:52Z`.
- Licensing basis: the pinned CC BY 4.0 license and nflverse scope statement expressly covering non-FTN release data, including PBP. Attribution and transformation notices are preserved in the source/report. Full source evidence remains in the local snapshot; see its README and `docs/nfl-real-historical-data.md` for the preceding investigation.

The verifier first checks the code-approved manifest digest, then every listed file's size/hash, then the raw bytes against both the saved release-asset digest and capture receipt. It checks asset identity, publication/revision/capture ordering, the approved capture time and the cached schedule observation. Missing files, symlinks, changed metadata/license/raw bytes, unknown manifests, conflicting timing or unknown source versions fail closed. File sizes and gzip expansion are bounded; duplicate JSON keys and duplicate CSV headers are rejected. No source reference is followed over the network and no saved Python script is imported/executed.

This is a reviewed content/version approval, **not a universal nflverse whitelist**. A new capture requires a separate reviewed registry change. Caller JSON, current file mtime, a current download URL, `license.status: approved`, a forged capture flag or a recomputed caller hash cannot approve new bytes. The approved capture record is a trusted local provenance anchor, not a third-party signed timestamp authority or an independent legal warranty.

## Completion and record validation

Only the verified loader can issue the internal, immutable `_VerifiedEvidence` object. It binds canonical hashes of the exact normalized records **and** their complete source metadata. The shared engine accepts `observed_game_result` only with that matching in-process evidence. JSON and boolean/dictionary approval flags cannot carry it; altered records or changed source metadata fail. Trusted Python code and the code-owned registry are inside the trust boundary, as are ordinary software modifications; this is not a sandbox against arbitrary code execution in the same interpreter.

The new record has `started_at`, `completed_no_later_than`, `status: final`, source-verified scores, neutral-site classification, and a completion evidence object containing the source `END GAME` marker, play ID, physical CSV ending-line number and original raw hash. It has **no `completed_at` field**. Report lineage explicitly emits `completed_at: null`, `completion_basis: observed_complete_by_snapshot`, and the observed upper bound.

Requirements:

1. A unique terminal `END GAME` marker must be the game's last source row. Play identities, team/date/week/season/venue/final-score metadata must not conflict. Source end totals must agree with final score fields.
2. Actual prior-game start is taken from a timestamped kickoff event, not guessed from a scheduled clock or game date. Its Eastern calendar day must agree with the source game date and NFL starting-year season convention.
3. All used timed events must precede capture. The bound must equal the verified source capture and satisfy `started_at < completed_no_later_than < cutoff`. Equality at cutoff is unavailable.
4. Snapshot publication, revision, availability/capture and the cached target schedule observation must all be eligible before cutoff. A completion *upper bound* later than the asset revision is not mistaken for an actual completion after revision; it is checked as observational evidence instead.
5. Targets are excluded before reading their score/status values, including disguised SF/WAS target-day records. Later-dated records are excluded. Missing/incomplete games, conflicting IDs/status/scores, unverifiable clocks or any mismatch with the reviewed SF/WAS prior-game inventory block acceptance.
6. After normalization, the shared engine must accept the complete reviewed game-ID set with no excluded evidence. A provider-level verification pass cannot be reported as accepted history if downstream validation rejects it.

Ordinary `game_result` still requires an exact, aware `completed_at` and its existing revision/cutoff checks. Ordinary scheduled fixtures still require a boolean neutral-site value. The new evidence-gated schedule record permits an explicit unknown neutral-site value rather than inventing one; target venue uncertainty stays visible. Exact and bounded copies of the same game share duplicate identity handling and are both quarantined.

## Schedule, completeness and missing context

The reviewed schedule context comes from pinned cached official 49ers schedule excerpts observed `2026-10-19T05:36:11.361532+00:00`, not a fresh NFL feed. The normalized event is Washington at SF, October 19, 17:15 PDT / 20:15 EDT (`2026-10-20T00:15:00Z`). The SF cutoff is `2026-10-19T23:00:00Z`. The target schedule is accepted only as a reviewed factual reference; no scraping/redistribution license for underlying NFL website content is implied or mislabeled CC BY. Its timestamps describe the cached observation/version, not the remote page's original announcement time.

Actual target kickoff remains unknown; the report is prospective. The target's physical neutral-site status is not established by the excerpts and remains unknown, although home designation is recorded. Prior games' own `location` values separately establish their home/away/neutral splits.

The code-reviewed prior-game inventory matches five game IDs per team. This is not independently reconciled full-season completeness. Opponent-strength values are explicitly withheld because the accepted subset is not a certified league-wide opponent-history inventory. Injuries, rosters, starters, subsequent updates, calibrated predictive methods and prices remain missing. No values are generated for those gaps. Historical record fractions are descriptive sample statistics, **not target win probabilities**.

## Actual real-data outputs

These files were generated by the real module CLI, not hand-authored assessment responses:

- `docs/nfl-observed-49ers-report.json` and `.txt`: `ACCEPTED_OBSERVED_HISTORY`; ten accepted prior records; five per team; actual kickoff unknown. Selection assessment remains `INSUFFICIENT_DATA` because descriptive availability is not a validated prediction.
- `docs/nfl-observed-rams-report.json` and `.txt`: `BLOCKED`, `snapshot_not_before_cutoff`, zero accepted records/metrics. The October 19 capture cannot establish an October 18 pregame view; game parsing is not invoked for that late-capture request.

| Captured history | SF | Washington |
| --- | --- | --- |
| W–L–T | 5–0–0 | 1–3–1 |
| Points scored / allowed | 154 / 93 | 115 / 149 |
| Per-game scored / allowed | 30.8 / 18.6 | 23.0 / 29.8 |
| Point differential | +61 | -34 |
| Non-neutral home W–L–T | 3–0–0 | 1–0–1 |
| Non-neutral away W–L–T | 1–0–0 | 0–2–0 |
| Neutral W–L–T | 1–0–0 | 0–1–0 |

These are accepted source-history descriptions, not estimated winning probabilities, fair contract prices, EV, or recommendations. No retrospective Rams statistics are substituted and no joint combo assessment is claimed.

## Verification

    .venv/bin/python -m unittest discover -s tests -p 'test_*.py'

All **180 offline tests passed: 155 existing plus 25 new observed-snapshot tests**. Existing tests/fixtures are untouched. New tests use explicitly synthetic temporary bundles and a mocked trusted registry; they do not depend on the untracked real dataset or claim those toy values are real statistics. The separate actual CLI runs above verify acceptance of this machine's genuine snapshot.

Regressions cover bounds versus exact timestamps, cutoff equality/late captures, Rams refusal before parsing, missing/forged timing, integrity/license evidence, target/future-information exclusion, incomplete/duplicate/conflicting records, neutral venues, source/record binding, rejection of caller flags, exact/bounded duplicate identity, strict old fixtures, downstream rejection, JSON/readable CLI execution, and isolation from network/database/credential access. Final staged whitespace/security checks and independent review precede the local commit. No dependencies, models, trades, Kalshi calls, Docker/n8n/bot/Hermes changes, merges or pushes are part of this milestone.
