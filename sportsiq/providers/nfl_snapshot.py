"""Pinned, offline nflverse PBP verification; no caller-controlled approval switch."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsiq.analysis.nfl import assess_nfl, _instant, _source_metadata

# This is a reviewed capture/content approval, not a provider-wide whitelist.
# New captures require a code-reviewed registry entry, never a JSON approval flag.
APPROVED_SNAPSHOTS = {
    'd453d38c8d50086b9e2ce3dbb798d1bf57f981a9dd58025b4cf2c0a4ff15e9ee': {
        'manifest_sha256': '5f4499d065c659bbf674ef5a3595f87eb3d9d5deac6ba8c9f95b6450ff4493df',
        'capture_at': '2026-10-19T05:34:44.001488+00:00', 'asset_id': 655240352,
        'expected_history': {
            'SF': ['2026_01_SF_LA', '2026_02_MIA_SF', '2026_03_ARI_SF', '2026_04_DEN_SF', '2026_05_SF_SEA'],
            'WAS': ['2026_01_WAS_PHI', '2026_02_WAS_DAL', '2026_03_SEA_WAS', '2026_04_IND_WAS', '2026_05_NYG_WAS'],
        },
        'schedule_observed_at': '2026-10-19T05:36:11.361532+00:00',
        'scheduled_kickoff': '2026-10-20T00:15:00Z',
        'license_review': 'CC BY 4.0: pinned license and nflverse scope statement include non-FTN PBP; attribution retained',
    },
}
_SEAL = object()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True, init=False)
class _VerifiedEvidence:
    """In-process capability bound to verified source and record bytes, not JSON flags."""
    pairs: frozenset

    def __init__(self, seal, sources, cutoff):
        if seal is not _SEAL:
            raise ValueError('verification capability is internal')
        pairs = []
        for source in sources:
            metadata = _source_metadata(source, 'observed', cutoff)
            pairs.extend((_hash(metadata), _hash(record)) for record in source['records'])
        object.__setattr__(self, 'pairs', frozenset(pairs))

    def permits(self, record, metadata):
        return (_hash(metadata), _hash(record)) in self.pairs


def _json(body):
    def obj(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate metadata key')
            result[key] = value
        return result
    return json.loads(body, object_pairs_hook=obj)


def _read(path, maximum):
    if path.is_symlink() or not path.is_file():
        raise ValueError('snapshot_file_missing_or_symlink')
    with path.open('rb') as stream:
        body = stream.read(maximum + 1)
    if len(body) > maximum:
        raise ValueError('snapshot_file_too_large')
    return body


def _bundle(path):
    manifest_body = _read(path / 'snapshot_manifest.json', 200000)
    manifest = _json(manifest_body)
    raw_hash = manifest.get('raw_dataset_sha256')
    approval = APPROVED_SNAPSHOTS.get(raw_hash) if isinstance(raw_hash, str) else None
    if not approval or hashlib.sha256(manifest_body).hexdigest() != approval['manifest_sha256']:
        raise ValueError('snapshot_not_code_approved')
    files = {}
    for entry in manifest['files']:
        name = entry['file']
        if not isinstance(name, str) or Path(name).name != name or name in files:
            raise ValueError('invalid_snapshot_file_inventory')
        body = _read(path / name, 10000000 if name.endswith('.csv.gz') else 1000000)
        if len(body) != entry['bytes'] or hashlib.sha256(body).hexdigest() != entry['sha256']:
            raise ValueError('snapshot_integrity_failure')
        files[name] = body
    raw = files['play_by_play_2026.csv.gz']
    capture = _json(files['capture.json'])['asset']
    assets = _json(files['pbp_release.json'])['assets']
    matching = [a for a in assets if a['id'] == approval['asset_id'] and a['name'] == 'play_by_play_2026.csv.gz']
    if len(matching) != 1:
        raise ValueError('ambiguous_release_asset')
    asset = matching[0]
    if (hashlib.sha256(raw).hexdigest() != raw_hash or capture['sha256'] != raw_hash
            or asset['digest'] != 'sha256:' + raw_hash or capture['publisher_digest'] != asset['digest']
            or asset['size'] != len(raw) or capture['bytes'] != len(raw)
            or capture['response_status'] != 200 or capture['publisher_asset_id'] != asset['id']
            or _instant(capture['retrieved_at']) != _instant(approval['capture_at'])
            or _instant(capture['publisher_updated_at']) != _instant(asset['updated_at'])
            or not _instant(asset['created_at']) <= _instant(asset['updated_at']) <= _instant(capture['retrieved_at'])
            or not _instant(capture['request_started_at']) <= _instant(capture['retrieved_at'])):
        raise ValueError('source_timing_or_digest_conflict')
    if not files['data_license.md'].startswith(b'Attribution 4.0 International') or b'CC-BY 4.0' not in files['org_readme.md']:
        raise ValueError('license_evidence_missing')
    schedule = _json(files['schedule_reference.json'])
    if _instant(schedule['checked_at']) != _instant(approval['schedule_observed_at']):
        raise ValueError('schedule_observation_conflict')
    return approval, raw_hash, raw, capture, asset


def _source(path, sid, version, observed_at, published_at, revised_at, records, reference):
    return {
        'source_id': sid, 'data_kind': 'observed', 'provider': 'Verified pinned nflverse capture',
        'reference': reference, 'version': version, 'reliable': True,
        'reliability_evidence': 'Pinned bundle rehashed; saved publisher digest and final-marker rows verified',
        'license': {'status': 'approved', 'reference': (path / 'data_license.md').as_uri(),
                    'allowed_uses': ['analysis', 'display'],
                    'attribution': 'nflverse/nflfastR; upstream NFL PBP; CC BY 4.0; SportsIQ derived projection, no endorsement'},
        'published_at': published_at, 'revision_at': revised_at, 'available_at': observed_at,
        'retrieved_at': observed_at, 'availability_evidence': {
            'kind': 'capture', 'reference': (path / 'snapshot_manifest.json').as_uri(), 'observed_at': observed_at},
        'records': records, 'content_sha256': _hash(records),
    }


def _records(raw, approval, raw_hash, captured_at):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        body = stream.read(64000001)
    if len(body) > 64000000:
        raise ValueError('uncompressed_snapshot_too_large')
    reader = csv.DictReader(io.StringIO(body.decode('utf-8'), newline=''), strict=True)
    required = {'game_id', 'home_team', 'away_team', 'game_date', 'week', 'season', 'season_type',
                'location', 'home_score', 'away_score', 'total_home_score', 'total_away_score',
                'desc', 'play_type', 'time_of_day', 'play_id'}
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or not required <= set(reader.fieldnames):
        raise ValueError('pbp_schema_invalid')
    groups, excluded = defaultdict(list), set()
    for row in reader:
        if None in row or any(row.get(k) is None for k in required):
            raise ValueError('pbp_record_incomplete')
        pair = {row['home_team'], row['away_team']}
        # Exclude targets before interpreting their scores or terminal status.
        if row['game_id'] in ('2026_06_WAS_SF', '2026_06_ARI_LA') or (
                pair == {'SF', 'WAS'} and row['game_date'] == '2026-10-19'):
            excluded.add(row['game_id'])
            continue
        if not pair.intersection(('SF', 'WAS')):
            continue
        if row['game_date'] >= '2026-10-19':
            excluded.add(row['game_id'])
            continue
        row['_line'] = reader.line_num
        groups[row['game_id']].append(row)
    records, lineage = [], []
    for gid, plays in groups.items():
        if any(not r['play_id'].strip() for r in plays) or len({r['play_id'] for r in plays}) != len(plays):
            raise ValueError('conflicting_play_identity')
        keys = ('home_team', 'away_team', 'game_date', 'week', 'season', 'season_type', 'location', 'home_score', 'away_score')
        if len({tuple(r[k] for k in keys) for r in plays}) != 1:
            raise ValueError('conflicting_game_metadata')
        first = plays[0]
        if first['season'] != '2026' or first['season_type'] != 'REG' or not 1 <= int(first['week']) <= 5:
            raise ValueError('prior_game_scope_conflict')
        if first['location'] not in ('Home', 'Neutral') or first['home_team'] == first['away_team']:
            raise ValueError('venue_or_team_identity_unverified')
        ends = [r for r in plays if r['desc'].strip().upper() == 'END GAME']
        if len(ends) != 1 or plays[-1] is not ends[0]:
            raise ValueError('final_status_missing_or_conflicting')
        end = ends[0]
        starts = [_instant(r['time_of_day']) for r in plays if r['play_type'] == 'kickoff' and r['time_of_day']]
        timed = [_instant(r['time_of_day']) for r in plays if r['time_of_day']]
        if not starts or not timed or max(timed) >= _instant(captured_at):
            raise ValueError('event_timing_unverified')
        gameday = date.fromisoformat(first['game_date'])
        season = gameday.year - 1 if gameday.month <= 2 else gameday.year
        if season != 2026 or min(starts).astimezone(ZoneInfo('America/New_York')).date() != gameday:
            raise ValueError('event_date_or_season_conflict')
        hp, ap = int(end['home_score']), int(end['away_score'])
        if not 0 <= hp <= 200 or not 0 <= ap <= 200 or hp != int(end['total_home_score']) or ap != int(end['total_away_score']):
            raise ValueError('final_score_conflict')
        record = dict(kind='observed_game_result', game_id=gid, season=2026, season_type='REG',
                      home_team_id=first['home_team'], away_team_id=first['away_team'],
                      home_points=hp, away_points=ap, neutral_site=first['location'] == 'Neutral',
                      started_at=min(starts).isoformat(), completed_no_later_than=captured_at, status='final',
                      completion_evidence={'basis': 'END GAME', 'play_id': end['play_id'],
                                           'csv_ending_line': end['_line'], 'raw_sha256': raw_hash})
        records.append(record)
        lineage.append(dict(game_id=gid, completion_basis='observed_complete_by_snapshot',
                            completed_at=None, completed_no_later_than=captured_at,
                            started_at=record['started_at'], basis='END GAME', play_id=end['play_id'],
                            csv_ending_line=end['_line'], raw_sha256=raw_hash))
    records.sort(key=lambda r: r['game_id'])
    lineage.sort(key=lambda r: r['game_id'])
    for team, expected in approval['expected_history'].items():
        actual = {r['game_id'] for r in records if team in (r['home_team_id'], r['away_team_id'])}
        if actual != set(expected):
            raise ValueError('reviewed_snapshot_inventory_incomplete')
    return records, lineage, sorted(excluded)


def assess_snapshot(directory, *, cutoff, selection='49ers'):
    """Verify pinned bytes and submit separately typed observed evidence to the engine."""
    instant = _instant(cutoff)
    if selection not in ('49ers', 'rams'):
        raise ValueError('unsupported selection')
    sf = selection == '49ers'
    analysis = {'schema_version': 1, 'data_kind': 'observed', 'mode': 'prospective' if sf else 'historical',
                'analysis_cutoff': instant.isoformat(), 'teams': {'SF': 'San Francisco 49ers', 'WAS': 'Washington Commanders',
                    'LA': 'Los Angeles Rams', 'ARI': 'Arizona Cardinals'},
                'legs': [dict(leg_id=selection, game_id='2026_06_WAS_SF' if sf else '2026_06_ARI_LA',
                              market_ticker='KXNFLGAME-26OCT19WASSF-SF' if sf else 'KXNFLGAME-26OCT18ARILAR-LAR',
                              side='yes', selected_team_id='SF' if sf else 'LA')], 'sources': []}
    verified_bundle = None
    try:
        path = Path(directory).resolve()
        approval, raw_hash, raw, capture, asset = _bundle(path)
        verified_bundle = (raw_hash, capture['retrieved_at'])
        # A late capture cannot certify a retrospective pregame view, regardless of old game dates.
        if _instant(capture['retrieved_at']) >= instant:
            raise ValueError('snapshot_not_before_cutoff')
        if not sf:
            raise ValueError('rams_historical_context_not_approved')
        if _instant(approval['schedule_observed_at']) >= instant or instant >= _instant(approval['scheduled_kickoff']):
            raise ValueError('cutoff_or_schedule_not_pregame')
        records, lineage, excluded = _records(raw, approval, raw_hash, capture['retrieved_at'])
        for record in records:
            for team in (record['home_team_id'], record['away_team_id']):
                analysis['teams'].setdefault(team, team)
        source = _source(path, 'verified-nflverse-pbp', raw_hash, capture['retrieved_at'],
                         asset['created_at'], asset['updated_at'], records, (path / 'play_by_play_2026.csv.gz').as_uri())
        schedule_record = dict(kind='observed_scheduled_game', game_id='2026_06_WAS_SF', season=2026,
                               season_type='REG', home_team_id='SF', away_team_id='WAS', neutral_site=None,
                               scheduled_kickoff=approval['scheduled_kickoff'])
        observed = approval['schedule_observed_at']
        schedule = _source(path, 'verified-cached-schedule', approval['manifest_sha256'], observed,
                           observed, observed, [schedule_record], (path / 'schedule_reference.json').as_uri())
        # Schedule event facts are a separate reviewed reference, not nflverse data
        # and not a claim to hold a scraping/redistribution license for NFL pages.
        schedule.update(provider='SportsIQ pinned official-schedule excerpt facts',
                        reliability_evidence='Pinned cached source and explicitly reviewed event-fact transcription')
        schedule['license'] = {
            'status': 'approved', 'reference': 'reviewed-event-facts:' + approval['manifest_sha256'],
            'allowed_uses': ['analysis', 'display'],
            'attribution': 'Official 49ers schedule, cached excerpt reference only; underlying content rights reserved',
        }
        analysis['sources'] = [source, schedule]
        evidence = _VerifiedEvidence(_SEAL, analysis['sources'], instant)
        result = assess_nfl(analysis, observed_evidence=evidence)
        record_metric = next((m for m in result['legs'][0]['metrics'] if m['name'] == 'record'), None)
        expected_ids = set().union(*(set(ids) for ids in approval['expected_history'].values()))
        if (result['excluded'] or not record_metric or record_metric['status'] != 'AVAILABLE'
                or set(record_metric['game_ids']) != expected_ids):
            raise ValueError('engine_rejected_verified_records')
        # The snapshot proves these histories, not independent league-wide opponent completeness.
        for leg in result['legs']:
            leg['uncertainty'].extend(['Schedule is a pinned cached excerpt, not a live refresh; target neutral-site status unknown',
                                       'Completion is observed by capture, not an exact final-whistle timestamp'])
            for metric in leg['metrics']:
                if metric['name'] == 'opponent_strength':
                    metric.update(status='MISSING', selected=None, opponent=None, source_ids=[], game_ids=[])
                elif metric['name'] == 'points':
                    for side in ('selected', 'opponent'):
                        values = metric[side]
                        if values:
                            difference = values['scored'] - values['allowed']
                            values.update(point_differential=difference,
                                          point_differential_per_game=round(difference / values['games'], 6))
            leg['missing_data'].append('independent_opponent_history_unverified')
        result['notice'] = ('Observed NFL history from a code-approved, hash-verified offline snapshot; '
                            'completion established by capture, not exact final-whistle timestamps')
        result.update(snapshot_status='ACCEPTED_OBSERVED_HISTORY', raw_snapshot_sha256=raw_hash,
                      snapshot_captured_at=capture['retrieved_at'], completion_provenance=lineage,
                      reviewed_inventory='matched; independent full-season coverage remains unverified',
                      target_and_later_games_excluded=excluded, license_review=approval['license_review'])
        return result
    except (OSError, ValueError, TypeError, KeyError, OverflowError, csv.Error, EOFError) as error:
        # Deliberately sanitize paths, source values and arbitrary exception text.
        reason = 'snapshot_verification_failed'

        if isinstance(error, ValueError) and str(error) in {
                'snapshot_not_code_approved', 'snapshot_integrity_failure', 'snapshot_not_before_cutoff',
                'rams_historical_context_not_approved', 'cutoff_or_schedule_not_pregame',
                'reviewed_snapshot_inventory_incomplete', 'conflicting_game_metadata',
                'final_status_missing_or_conflicting', 'event_timing_unverified', 'final_score_conflict',
                'conflicting_play_identity', 'engine_rejected_verified_records'}:
            reason = str(error)
        analysis['sources'] = []
        result = assess_nfl(analysis)
        result.update(snapshot_status='BLOCKED', completion_provenance=[], snapshot_missing_evidence=[reason])
        if verified_bundle:
            result.update(raw_snapshot_sha256=verified_bundle[0], snapshot_captured_at=verified_bundle[1])
        for leg in result['legs']:
            leg['missing_data'].append(reason)
        return result
