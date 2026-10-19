# Milestone 2E-A: NFL pregame data availability audit

Audit date: October 19, 2026, UTC. Read-only research; no predictions, probabilities, trading, or ingestion implementation. This document is an internal capability/permission assessment, not an approved data feed or a backtest.

## Repository prerequisite and scope

Verified locally on `main`: HEAD `76dbd99d7f4e934ef133018ef8918d98325c6e6e` is Milestone 2D and is an ancestor of main; working tree clean. The existing offline suite passed **104 tests** before creating `feature/nfl-pregame-data-audit` from main. The branch did not previously exist. Only this documentation file is changed.

The existing 2D artifacts identify these exact YES selections, not a newly constructed two-leg Kalshi product:

| Selection | Exact leg market | Provider identity / venue direction |
| --- | --- | --- |
| Los Angeles Rams YES, October 18 | `KXNFLGAME-26OCT18ARILAR-LAR` | BALLDONTLIE `1392304`; ARI away at LAR home; nflverse `2026_06_ARI_LA` |
| San Francisco 49ers YES, October 19 | `KXNFLGAME-26OCT19WASSF-SF` | BALLDONTLIE `1392308`; WAS away at SF home; nflverse `2026_06_WAS_SF` |

Original combo event: `KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y`; selected market: `KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y-RXGIQQ2OG`. It contains 12 selections, including 10 college legs, per `docs/nfl-market-matching.md` and the observed fixture. That fixture is explicitly not a pregame capture. Preserve `LA`/`LAR` and `WAS`/`WSH` crosswalks explicitly; never join by ticker date alone.

## Time contract and evidence matrix

Clock check: `2026-10-19T01:05:15Z` (October 18, 21:05:15 EDT). Retrieval times below are observations made during this audit, not historical publication times. All feature inclusion must satisfy `available_at < cutoff`, and the cutoff must precede verified kickoff. A later source may establish chronology for audit validation but its contents cannot become earlier decision inputs.

| Evidence | Rams vs Cardinals | 49ers vs Commanders |
| --- | --- | --- |
| Scheduled kickoff | October 18, 16:05 EDT / `2026-10-18T20:05:00Z`, corroborated by pinned nflverse schedule | October 19, 20:15 EDT / `2026-10-20T00:15:00Z`, corroborated by the same pinned schedule |
| Historical schedule candidate | Commit `a47cea5df8c3aae60e2ab9f6181cd4515767ffd2`, committer time `2026-10-18T18:15:15Z`; both target score fields empty | Same version and empty target score fields |
| Actual kickoff evidence | Current PBP identifies first kickoff, play `39`, at `2026-10-18T20:05:18.150Z`; gamebook records start at 13:05 PDT, corroborating the minute | Not yet played at audit time; actual kickoff does not exist in the inspected PBP and is not verified |
| Analysis cutoff | `C_LAR = 2026-10-18T19:00:00Z` (15:00 EDT), strictly before observed actual kickoff | `C_SF = 2026-10-19T23:00:00Z` (19:00 EDT), **prospective**, before scheduled start only; revalidate against actual start later |
| Schedule publication assurance | Immutable Git version retrieved, but committer timestamp alone does not independently prove when it became publicly available | Same limitation; current local capture predates prospective cutoff, but future schedule changes remain possible |
| Team-game history coverage | Pinned schedule has five earlier completed regular-season records for each of LA and ARI before October 18 | Five each for SF and WAS under the same conservative date exclusion |
| Latest PBP eligibility | 2026 release updated October 19, 00:09:58Z: after `C_LAR`, so not a certified pre-cutoff feature snapshot | Retrieved before prospective `C_SF`; only prior completed games and captured versions could qualify if kickoff remains later |
| Injuries / rosters | 2026 files exist; publisher updates October 18, 12:02:07Z / 12:04:08Z, but exact pre-cutoff bytes and report-publication provenance need validation | Same files captured before prospective cutoff; do not substitute later Monday updates or eventual inactives |
| Price evidence | Bounded pre-cutoff trades and completed candles technically returned; rights blocked | Partial observations exist only through audit time; no claim to know the future `C_SF` price |

Schedule and commit evidence support the scheduled times, identities, and record counts.[33][50]

PBP supports the first-kickoff timestamp, while the official gamebook only corroborates minute-level start time; neither source was available to this audit before `C_LAR`.[26][43]

Release metadata supports file freshness, not immutable historical contents or per-report publication times.[1][2][3]

The Rams game is historical at audit time; no result, target-game score, final lineup, or settlement value is used or reproduced. The 49ers game is still upcoming, not settled. It is impossible to claim an actual-kickoff-verified historical assessment for it now. Do not convert its Kalshi occurrence time (`2026-10-20T03:15:00Z`) into kickoff; the analogous Rams occurrence is also not kickoff (2D evidence).

For an analytical comparison of these **two NFL selections only**, use common cutoff `C_PAIR = C_LAR`; do not let Sunday results inform the original pair decision. This does **not** establish a valid original 12-leg combo cutoff: that must precede its earliest college kickoff, none of which this NFL audit verifies. A separate Monday decision can have its own cutoff, but must not be relabeled an original combo assessment.

## Source comparison: accessibility is not permission

| Source / exact access route | Coverage verified | Freshness and snapshots | Rights / limitations | Verdict |
| --- | --- | --- | --- | --- |
| nflverse PBP: unauthenticated GitHub release API tag `pbp`; direct `play_by_play_2026.csv.gz`; documented `load_pbp(2026)` | Release assets enumerate 1999–2026; downloaded 2026 file has 16,018 rows, 91 game IDs, game dates through October 18; not a completeness guarantee | Documented nightly/game-day refresh and later stat corrections. Current 2026 asset updated October 19, 00:09:58Z; mutable annual release, not an as-of archive | nflverse-data repository carries CC BY 4.0: attribute, link license, identify changes; upstream rights/exceptions still require review | Best broad technical basis; historical version gate required.[1][6][18] |
| nflverse/Lee Sharpe schedules: `load_schedules()` source points to nfldata `games.rds`; audit used corresponding `data/games.csv`, plus commit-pinned CSV | Current CSV seasons 1999–2026; pinned version corroborates both Week 6 games | Documented five-minute in-season updates; Git history can recover versions, unlike a current final schedule | nfldata root listing/README did not establish a data license; guessed `/LICENSE` returned 404. Do not apply nflverse-data's separate repository license automatically | Strong technical snapshot candidate; licensing and public-availability evidence unresolved.[7][18][44] |
| nflverse injuries: release tag `injuries`, direct `injuries_2026.csv`, documented loader | Asset seasons 2009–2026; actual file covers Weeks 1–6; Week 6 rows: ARI 11, LA 11, SF 19, WAS 22 | Daily 07:00 UTC is documented cadence; observed publisher timestamp differs. Downloaded schema has no report publication timestamp or daily revision date | CC BY 4.0 repository terms, subject to upstream rights; weekly status is not a historical sequence of daily reports | Exists in 2026; cannot certify historical report state from season/week alone.[3][6][18] |
| nflverse rosters: release tag `rosters`, direct `roster_2026.csv` | Assets enumerate 1920–2026, with no claim of uniform early-season detail; downloaded file has 3,043 rows and week/status/IDs, but no status-effective timestamp | Daily 07:00 UTC documented; observed asset update October 18, 12:04:08Z. Season file is mutable | Same repository attribution/upstream qualification; active-roster status is not proof of game-day availability or starting role | Useful identity crosswalk; strict as-of membership conditional.[2][6][32] |
| nflverse depth charts: release tag `depth_charts`; `depth_charts_2026.csv` / `.parquet` / `.rds` | Assets enumerate 2001–2026; 2026 CSV asset is 63,678,279 bytes; not downloaded | Since 2025, documented append-by-ISO8601 `dt`, not week assignment; this is a positive snapshot mechanism, though historical revisions still need checking | Repository license/upstream review; depth rank is not a verified starter | Candidate later extension; actual relevant `dt` rows not validated in this bounded audit.[4][18][52] |
| Official NFL game pages/gamebook and injury publications | Target gamebook was linked by Rams game center; no authorized, documented public NFL stats/injury API verified | Postgame gamebook can validate kickoff, never pregame lineups; an article date does not prove an unchanged historical body | NFL terms restrict systematic retrieval/commercial reuse; gamebook restricts non-media use without permission. Stop at reference verification; do not build a scraper or bulk gamebook feature store | Authority for reference checks, not an approved ingestion feed.[24][26][27] |
| Kalshi documented public API | Exact two legs and exact mixed combo were technically accessible in bounded GETs; public quickstart does not require authentication | Trades have execution timestamps; candles have inclusive period ends; current market metadata is not a historical orderbook | Developer Agreement §3/§3.1 restricts API collection/storage to own trading and third-party sharing; data terms also restrict software/AI use. Public access is not a research license | **Blocked for SportsIQ ingestion/modeling pending written permission or an applicable license.**[49][53][54] |

No paid endpoint, account endpoint, private key, or undocumented NFL feed was called. BALLDONTLIE was not re-queried: 2D supplies matching evidence only, not entitlement to historical stats or snapshots. No PFR/ESPN scraping was performed. Official team injury articles were discovered in search but not fetched into a feature dataset after the rights restrictions became clear.

## Metric implementation and cutoff requirements

Difficulty is relative to a future small offline prototype: low = deterministic CSV aggregation; medium = careful joins/schema/version handling; high = missing archives or permission work. These are proposed definitions, not implemented metrics. Every row inherits the rights restrictions of its source in the preceding comparison.

| Metric / proposed definition | Exact retrieval method and coverage | Historical-cutoff validation | Licensing / difficulty / usability |
| --- | --- | --- | --- |
| Team records: W/L/T and win percentage `(W + T/2) / games` | GET commit list with `path=data/games.csv&until=<cutoff>&per_page=1`; GET `raw.githubusercontent.com/nflverse/nfldata/<sha>/data/games.csv`; filter 2026 REG and explicit team IDs | Require snapshot publication evidence before cutoff and completed prior games. For first prototype exclude **all** games dated October 18 or later; this conservatively omits some legitimately available Sunday results for Monday. Never count target games, blank scores, byes, or live games | nfldata rights unresolved; low; reconstructable, not yet approved/certified.[33][50] |
| Home/away W/L/T | Same pinned CSV; split on explicit `home_team`/`away_team`, not `vs` text | Same completed-game set; do not treat neutral-site home designation as a physical home-field advantage | Same rights; low; conditionally usable with neutral-site flag.[50] |
| Offensive efficiency: points per prior game and yards per eligible scrimmage play | Pinned schedule for points; for yards GET version-approved PBP CSV/GZIP, identify `posteam`, `yards_gained`, `play_type` and specified denominator | Use only prior completed games and pre-cutoff data versions; define kneel/spike/penalty exclusions. Observed 2026 schema has no `no_play` column: do not assume it exists or count penalty nullifiers blindly | Schedule vs PBP rights differ; medium; points first, PBP yards only after schema/version gates.[43][50] |
| Defensive efficiency: points allowed/game and yards allowed/play | Same versions; reverse opponent score and join PBP by `defteam` | Same temporal restrictions and exclusions; distinguish offensive points allowed from total scoreboard points if later offering that definition | Same licenses; medium; conditional, no unqualified current season totals.[43][50] |
| EPA/play and success rate | PBP columns `epa`, `success`, `posteam`, `defteam`; documented loader `load_pbp(2026)` or direct release download | Require pre-cutoff PBP bytes **and** EPA algorithm/model artifact/training provenance available by cutoff; definitions and denominator must be frozen. Selecting old games from a newly corrected file does not satisfy this | CC BY 4.0 plus upstream checks; high; **defer EPA**, do not train or load a prediction model here.[43][48] |
| Opponent strength: mean opponents' pre-cutoff win percentages | Same pinned schedule, league-wide prior completed REG games; compute opponent records with the target team's head-to-head games excluded; omit zero-game opponents with explicit missingness/count | Use only the same as-of game universe for every opponent; never use eventual season record, full-season SOS, or future opponents' results | nfldata rights unresolved; medium; deterministic candidate after records pass gates.[50] |
| Injuries: documented practice participation and game designation | Direct `injuries_2026.csv`; filter `(season=2026, season_type=REG, week=6, team)`; 63 rows across the four teams | File has no report `published_at`; require an independently archived pre-cutoff report/version. Blank designation means unknown/unspecified, not healthy; never infer from final gamebook or actual participation | nflverse-data/upstream review and official-report permission if used; high; **not historically certified**.[31] |
| Roster membership / position / IDs | Direct `roster_2026.csv`; explicit team and `gsis_id` crosswalk; preserve week/status, not just names | Birth dates are not observation times. Need captured pre-cutoff membership/status version and effective transaction time; current season membership can include later changes | nflverse-data/upstream review; medium/high; IDs usable as metadata, availability conditional.[32] |
| Depth ordering | Listed release asset `depth_charts_2026.*`; inspect `dt` and choose latest eligible snapshot per team/position | Require `dt < cutoff`, trustworthy publication/version evidence, no later overwrite; `dt` denotes load time, not necessarily transaction time | Same repository/upstream review; medium; mechanism documented, relevant rows untested.[4][52] |
| Leg YES trade price / bid-ask candle | Documented public trade and candle paths in next section, exact ticker only | Execution time and complete candle end strictly before decision cutoff; require source-record publication assurance and stale/missing flags | Kalshi permission blocked; technical parsing medium; not approved implementation input.[21][22][53] |
| Combo historical price | Same APIs but exact combo ticker and `KXMVECROSSCATEGORY` series | Must predate earliest of **all 12** verified kickoffs for an original entry; never multiply leg prices or substitute a leg quote | Same legal block; sparse history/dependence high; defer.[23][54] |

Availability decision: basic records, venue splits, points/game and simple opponent records are computationally feasible without a prediction engine, but not yet a fully licensed, point-in-time-certified assessment. For Rams, current PBP corrections cannot pass the historical version gate. Rosters/injuries need real snapshot provenance; their 2026 presence is verified, not their eligibility at every decision instant. EPA, injury impact scores, dependence, joint probabilities, and EV are out of scope.

## Kalshi history: verified mechanism, bounded coverage, legal stop

Documented base is `https://external-api.kalshi.com/trade-api/v2`. Exact requests and retrieval times are in the source receipts. Documentation specifies:[20][23]

- `GET /markets/{ticker}` for current/recent market metadata; `GET /historical/markets/{ticker}` after archival. Current bids, last price, close time, settlement, and lifecycle are not historical pregame entry prices.
- `GET /markets/trades?ticker=<exact>&min_ts=<unix>&max_ts=<unix>&limit=100`; page with returned cursor. Older trade executions route to `/historical/trades`, not private portfolio fills. The returned archive boundary was `2026-08-19T00:00:00Z` for market settlement and trade creation, so the tested October windows used live-tier history.[8][22]
- `GET /series/{series}/markets/{ticker}/candlesticks?start_ts=<unix>&end_ts=<unix>&period_interval=60&include_latest_before_start=false`; intervals 1, 60 or 1440 minutes are documented. Archived equivalent: `/historical/markets/{ticker}/candlesticks`. No promise of all-market coverage or reconstruction of orderbook depth follows from this route.[21][23]

The bounded probe used `max_ts = floor(min(proposed_cutoff, request-planning-time)) - 1`; all returned trade timestamps/tickers and candle-end timestamps were checked in code. The SF request ended at `2026-10-19T01:08:09Z`, not its future cutoff. This is coverage discovery, not a complete trading-history extraction.

| Exact market / window start | Trades observed | Hour candles observed | Coverage conclusion |
| --- | --- | --- | --- |
| Rams leg; October 15, 19:00Z to before `C_LAR` | 100; continuation cursor present | 72, ends October 15, 19:00Z through October 18, 18:00Z | Pregame observations exist; trades only one page, not complete.[35][36] |
| 49ers leg; October 16, 23:00Z through audit planning time | 100; continuation cursor present | 51, ends October 16, 23:00Z through October 19, 01:00Z | Partial prospective history, not Monday's entry price.[38][39] |
| Exact mixed combo; October 15, 19:00Z to before `C_LAR` | 1; empty cursor for this bounded window | 3, only 1 with non-null trade close | Sparse combo history technically exists, but this window is after earlier college legs began; no original 12-leg pregame price validated.[41][42] |

No pagination follow-up or archival-data request was made; historical routes were documentation-verified only. Empty cursor proves only the requested window/page sequence exhausted, not lifetime coverage. A trade is an executed transaction, not proof that our intended size could enter at that price. Candle bid/ask OHLC is not depth or guaranteed execution; null prices remain missing, synthetic carry-forward bars are excluded, and a candle intersecting/ending at or after cutoff is unavailable. All requested prices are YES-denominated; no reinterpretation of side or joint-probability assumption.[21][22]

**Permission stop:** a generic terms-page fetch returned HTTP 429 and was not bypassed. Official hosted Developer Agreement v1.1 and Data Terms PDFs were subsequently retrieved and read. Their API collection/storage and software/AI restrictions conflict with treating unauthenticated access as a free research license. Applicability or supersession requires explicit confirmation from Kalshi; no permission was established. Earlier technical probes occurred before this restriction was identified. No further Kalshi data requests, raw-price publication, or integration work followed discovery; this document records the limitation rather than claiming compliance from HTTP 200.[53][54]

## Smallest recommended 2E-B (proposal only)

Build only a **fixture-first offline evidence gate and descriptive team-history report**, after separate approval to begin 2E-B:

1. Accept approved local schedule snapshots plus manifest: source URL, exact team/game IDs, source version/hash, publisher timestamp, independently evidenced availability time, retrieval time, rights/attribution, scheduled/actual kickoff provenance, cutoff, and precision/uncertainty. Keep event time, availability time, and retrieval time separate.
2. Fail closed on missing rights, actual-kickoff confirmation for a claimed historical replay, post-cutoff publication, mutable-only history, identity conflict, or incomplete required records. Label SF prospective until actual kickoff is verified; never silently certify it as historical. An approved pre-cutoff local capture can establish availability for a later prospective cutoff, but not a prior one.
3. Start with W/L/T, home/away W/L/T, points scored/allowed per game, and optional simple opponent-record strength using the conservative pre-October-18 completed-game set. Return missing/blocked reasons instead of fabricated numerical features. Use synthetic fixtures to test behavior while nfldata licensing/publication proof is unresolved.
4. Offline acceptance tests: cutoff equality rejected; UTC/Eastern rollover; ties; byes; incomplete/live games; duplicate IDs; future target scores ignored; current corrected snapshots rejected; zero-game opponents explicit; neutral venue flagged; unknown injury/roster timestamps fail closed; combo cutoff cannot reuse later-leg-only evidence.
5. Exclude live adapters, databases, models, EPA, injury weighting, probabilities, Kalshi-price ingestion, EV, and joint combo calculations. Add approved timestamped roster/injury/PBP/price evidence only in a later scope after permission and provenance gates pass.

**Verdict:** go for the proposed offline evidence/records scaffold; **no-go for a certified two-game historical pregame evaluation or price-based prediction prototype today**. Actual SF kickoff is still future, Rams historical feature versions are incomplete, nfldata reuse rights remain unverified, and Kalshi permission is blocked. These gaps are acceptance gates, not invitations to fill with present-day or settlement information.

## Verification and boundaries

Existing command, before and after the documentation change:

    .venv/bin/python -m unittest discover -s tests -p 'test_*.py'

Both runs: 104 tests passed. `git diff --check` and a staged documentation-only/secret-pattern review passed before commit. The suite is offline and does not validate third-party completeness, licenses, or historical kickoff evidence. No dependencies installed; existing source code, fixtures, databases, Docker, n8n, Kalshi bots, and Hermes configuration are unchanged. No merge or push.

Primary retrievals used stdlib GETs without credentials or paid endpoints; large depth-chart downloads were avoided. GitHub releases/assets, not their original 2022 release-container creation dates, supplied freshness evidence. No raw third-party datasets are committed. Exact observation receipts and selected content hashes below make the bounded checks reproducible without pretending that retrieval happened pregame.

## Retrieval receipts

`observed_at` is the UTC request-start clock time; HTTP success was then received. It is not the source publication time. Each numbered source resolves to the exact GET URL below; all requests were unauthenticated. Publisher/asset times are separately identified above. No season asset is claimed immutable merely because its current HTTP Last-Modified precedes a cutoff.

| Source | observed_at (request start) | HTTP |
| --- | --- | --- |
| [1] | `2026-10-19T01:06:24.542525+00:00` | 200 |
| [2] | `2026-10-19T01:06:24.545588+00:00` | 200 |
| [3] | `2026-10-19T01:06:24.547022+00:00` | 200 |
| [4] | `2026-10-19T01:06:24.547514+00:00` | 200 |
| [6] | `2026-10-19T01:06:24.747664+00:00` | 200 |
| [7] | `2026-10-19T01:06:24.749714+00:00` | 200 |
| [8] | `2026-10-19T01:06:24.785185+00:00` | 200 |
| [18] | `2026-10-19T01:07:19.317657+00:00` | 200 |
| [20] | `2026-10-19T01:07:19.319118+00:00` | 200 |
| [21] | `2026-10-19T01:07:19.319821+00:00` | 200 |
| [22] | `2026-10-19T01:07:19.320322+00:00` | 200 |
| [23] | `2026-10-19T01:07:19.395014+00:00` | 200 |
| [24] | `2026-10-19T01:07:19.482974+00:00` | 200 |
| [26] | `2026-10-19T01:08:10.129912+00:00` | 200 |
| [27] | `2026-10-19T01:08:10.130220+00:00` | 200 |
| [31] | `2026-10-19T01:08:10.150454+00:00` | 200 |
| [32] | `2026-10-19T01:08:10.204164+00:00` | 200 |
| [33] | `2026-10-19T01:08:10.214154+00:00` | 200 |
| [35] | `2026-10-19T01:08:10.319532+00:00` | 200 |
| [36] | `2026-10-19T01:08:10.334577+00:00` | 200 |
| [38] | `2026-10-19T01:08:10.445370+00:00` | 200 |
| [39] | `2026-10-19T01:08:10.458946+00:00` | 200 |
| [41] | `2026-10-19T01:08:10.559953+00:00` | 200 |
| [42] | `2026-10-19T01:08:10.571704+00:00` | 200 |
| [43] | `2026-10-19T01:09:08.659659+00:00` | 200 |
| [44] | `2026-10-19T01:09:08.660033+00:00` | 200 |
| [48] | `2026-10-19T01:09:08.770740+00:00` | 200 |
| [49] | `2026-10-19T01:09:08.816093+00:00` | 200 |
| [50] | `2026-10-19T01:09:08.854497+00:00` | 200 |
| [52] | `2026-10-19T01:10:18.551985+00:00` | 200 |
| [53] | `2026-10-19T01:10:44.885387+00:00` | 200 |
| [54] | `2026-10-19T01:10:44.885728+00:00` | 200 |

Selected downloaded-byte SHA-256 checks (audit receipts, not publication certificates):

- `schedule_snapshot`: `b6123914f2cd774cc0dcd004bdfc7a8764ee11d53c690b4742cea4241d4134e6`
- `pbp_gz`: `5cb2d43f52fe80e05b463cdcdc9c2772cc8b4b4c0781b1d836bd21cb56afda7e`
- `injuries_csv`: `b51b2ca4e3f6f40b8a53fc00b6689ab1d7c561d546a7cb1900dd74ee675e9286`
- `rosters_csv`: `5d13b1f597e2c700227703898543fad1b9b4bcd0eb304a24f8d59f3e1f847dff`
- `rams_gamebook`: `16b13616c8a9563a0a251bf299521439a83699385a254f6234559cab55acdccf`
- `kalshi_developer_agreement`: `9d3e33685c0f0a88d23895685107975b0745283aac96f8bf7d202f5ae4dc1fa6`
- `kalshi_data_terms`: `d19a0f94ffd65aa51eccb80cc8c9a06fb842478c5bf4cbd5a31ec51dd0a3966f`

## Sources

[1] https://api.github.com/repos/nflverse/nflverse-data/releases/tags/pbp
[2] https://api.github.com/repos/nflverse/nflverse-data/releases/tags/rosters
[3] https://api.github.com/repos/nflverse/nflverse-data/releases/tags/injuries
[4] https://api.github.com/repos/nflverse/nflverse-data/releases/tags/depth_charts
[6] https://raw.githubusercontent.com/nflverse/nflverse-data/main/LICENSE.md
[7] https://raw.githubusercontent.com/nflverse/nflreadr/main/R/load_schedules.R
[8] https://external-api.kalshi.com/trade-api/v2/historical/cutoff
[18] https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html
[20] https://docs.kalshi.com/getting_started/historical_data.md
[21] https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md
[22] https://docs.kalshi.com/api-reference/historical/get-historical-trades.md
[23] https://docs.kalshi.com/openapi.yaml
[24] https://www.nfl.com/games/cardinals-at-rams-2026-reg-6
[26] https://static.www.nfl.com/image/upload/v1792364768/gamecenter/aab58f7e-4feb-11f1-abca-2c54536568a9.pdf
[27] https://www.nfl.com/legal/terms
[31] https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2026.csv
[32] https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2026.csv
[33] https://api.github.com/repos/nflverse/nfldata/commits?path=data/games.csv&until=2026-10-18T19%3A00%3A00Z&per_page=1
[35] https://external-api.kalshi.com/trade-api/v2/markets/trades?ticker=KXNFLGAME-26OCT18ARILAR-LAR&min_ts=1792090800&max_ts=1792349999&limit=100
[36] https://external-api.kalshi.com/trade-api/v2/series/KXNFLGAME/markets/KXNFLGAME-26OCT18ARILAR-LAR/candlesticks?start_ts=1792090800&end_ts=1792349999&period_interval=60&include_latest_before_start=false
[38] https://external-api.kalshi.com/trade-api/v2/markets/trades?ticker=KXNFLGAME-26OCT19WASSF-SF&min_ts=1792191600&max_ts=1792372089&limit=100
[39] https://external-api.kalshi.com/trade-api/v2/series/KXNFLGAME/markets/KXNFLGAME-26OCT19WASSF-SF/candlesticks?start_ts=1792191600&end_ts=1792372089&period_interval=60&include_latest_before_start=false
[41] https://external-api.kalshi.com/trade-api/v2/markets/trades?ticker=KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y-RXGIQQ2OG&min_ts=1792090800&max_ts=1792349999&limit=100
[42] https://external-api.kalshi.com/trade-api/v2/series/KXMVECROSSCATEGORY/markets/KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y-RXGIQQ2OG/candlesticks?start_ts=1792090800&end_ts=1792349999&period_interval=60&include_latest_before_start=false
[43] https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.csv.gz
[44] https://api.github.com/repos/nflverse/nfldata/contents
[48] https://raw.githubusercontent.com/nflverse/nflreadr/main/R/load_pbp.R
[49] https://docs.kalshi.com/getting_started/quick_start_market_data.md
[50] https://raw.githubusercontent.com/nflverse/nfldata/a47cea5df8c3aae60e2ab9f6181cd4515767ffd2/data/games.csv
[52] https://nflreadr.nflverse.com/articles/dictionary_depth_charts.html
[53] https://assets.kalshi.com/Kalshi-Developer-Agreement.pdf
[54] https://kalshi-public-docs.s3.amazonaws.com/kalshi-data-terms-of-service.pdf
