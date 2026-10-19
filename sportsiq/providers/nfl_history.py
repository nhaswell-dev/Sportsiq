"""Offline CSV history normalization; real-data approval is deliberately not enabled."""

from copy import deepcopy
from collections import Counter
import csv
from datetime import date, datetime
import hashlib
import io
import json
import re
from zoneinfo import ZoneInfo

from sportsiq.analysis.nfl import (
    SOURCE_FIELDS, assess_nfl, _collect, _instant, _source_metadata, _validate_input, _validate_record,
)


REAL_DATA_BLOCKERS = [
    'real_dataset_not_approved', 'dataset_reuse_rights_unverified',
    'pre_cutoff_snapshot_publication_unverified', 'prior_game_completion_evidence_unverified',
]
CSV_FIELDS = {'game_id', 'season', 'game_type', 'gameday', 'gametime',
              'home_team', 'away_team', 'home_score', 'away_score'}
EASTERN = ZoneInfo('America/New_York')


def _hash(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _blocked(analysis, raw_hash, reasons):
    analysis = deepcopy(analysis)
    analysis['sources'] = []
    result = assess_nfl(analysis)
    for leg in result['legs']:
        leg['missing_data'].extend(reasons)
    result['historical_adapter'] = dict(status='BLOCKED', raw_snapshot_sha256=raw_hash,
                                        completeness={}, record_provenance=[], excluded=[], missing_evidence=reasons)
    return result


def _csv_rows(text):
    try:
        reader = csv.DictReader(io.StringIO(text), strict=True)
        fields = reader.fieldnames
        if not fields or len(set(fields)) != len(fields) or CSV_FIELDS != set(fields):
            raise ValueError('invalid CSV header')
        rows = [(reader.line_num, row) for row in reader]
    except csv.Error:
        raise ValueError('invalid CSV') from None
    if len(rows) > 10000 or any(None in r or any(v is None for v in r.values()) for _, r in rows):
        raise ValueError('invalid CSV rows')
    return rows


def _row_record(row, proof, snapshot, analysis, metadata, cutoff):
    fields = {'source_version', 'reference', 'started_at', 'completed_at', 'status', 'neutral_site'}
    if (not isinstance(proof, dict) or set(proof) != fields or proof['source_version'] != snapshot['version']
            or not isinstance(proof['reference'], str) or not proof['reference'].strip()):
        raise ValueError('row_provenance_missing_or_conflicting')
    if not all(re.fullmatch(r'[0-9]{1,3}', row[k]) for k in ('home_score', 'away_score')):
        raise ValueError('invalid_score')
    if not re.fullmatch(r'[0-9]{4}', row['season']):
        raise ValueError('invalid_season')
    # CSV date/time is scheduled Eastern time. Actual event times are supplied
    # independently; neither a duration nor midnight completion is invented.
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', row['gameday']) or not re.fullmatch(r'[0-9]{2}:[0-9]{2}', row['gametime']):
        raise ValueError('invalid_schedule_date')
    gameday = date.fromisoformat(row['gameday'])
    # NFL season labels use the starting year, not the calendar year of
    # January/February games. A label cannot move old results into this season.
    season = gameday.year - 1 if gameday.month <= 2 else gameday.year
    if int(row['season']) != season:
        raise ValueError('game_season_conflict')
    scheduled = datetime.fromisoformat(row['gameday'] + 'T' + row['gametime']).replace(tzinfo=EASTERN)
    started = _instant(proof['started_at'])
    if started.astimezone(EASTERN).date() != gameday or started < scheduled:
        raise ValueError('game_date_conflict')
    record = dict(kind='game_result', game_id=row['game_id'], season=int(row['season']),
                  season_type=row['game_type'], home_team_id=row['home_team'], away_team_id=row['away_team'],
                  home_points=int(row['home_score']), away_points=int(row['away_score']),
                  started_at=proof['started_at'], completed_at=proof['completed_at'],
                  status=proof['status'], neutral_site=proof['neutral_site'])
    _validate_record(record, analysis, metadata, cutoff)
    return record


def _coverage(manifest, snapshot, analysis, cutoff):
    coverage = manifest['coverage']
    if (not isinstance(coverage, dict) or set(coverage) != {'source_version', 'as_of', 'expected_game_ids'}
            or coverage['source_version'] != snapshot['version'] or _instant(coverage['as_of']) != cutoff
            or not isinstance(coverage['expected_game_ids'], dict)):
        raise ValueError('coverage_evidence_invalid')
    for team, ids in coverage['expected_game_ids'].items():
        if (team not in analysis['teams'] or not isinstance(ids, list)
                or not all(isinstance(g, str) and g.strip() for g in ids) or len(set(ids)) != len(ids)):
            raise ValueError('coverage_inventory_invalid')
    return coverage['expected_game_ids']


def assess_history(csv_text, manifest):
    """Adapt local source-shaped rows into the existing descriptive assessment engine."""
    fields = {'schema_version', 'analysis', 'snapshot', 'raw_sha256', 'row_evidence', 'coverage'}
    if (not isinstance(csv_text, str) or not isinstance(manifest, dict) or set(manifest) != fields
            or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
            or not isinstance(manifest['row_evidence'], dict)):
        raise ValueError('invalid historical manifest')
    analysis = deepcopy(manifest['analysis'])
    _validate_input(analysis)
    rows = _csv_rows(csv_text)
    raw_hash = hashlib.sha256(csv_text.encode()).hexdigest()
    # No independently approved real source exists for this milestone. An input
    # license.status string must not turn unresolved rights into permission.
    if analysis['data_kind'] != 'synthetic':
        return _blocked(analysis, raw_hash, list(REAL_DATA_BLOCKERS))
    for source in analysis['sources']:
        if (not isinstance(source, dict) or not isinstance(source.get('records'), list)
                or any(not isinstance(r, dict) or r.get('kind') not in ('scheduled_game', 'kickoff_verification')
                       for r in source['records'])):
            return _blocked(analysis, raw_hash, ['analysis_contains_unsupported_records'])
    if manifest['raw_sha256'] != raw_hash:
        return _blocked(analysis, raw_hash, ['raw_snapshot_hash_mismatch'])
    cutoff = _instant(analysis['analysis_cutoff'])
    snapshot = deepcopy(manifest['snapshot'])
    if not isinstance(snapshot, dict) or set(snapshot) != SOURCE_FIELDS - {'records', 'content_sha256'}:
        return _blocked(analysis, raw_hash, ['source_snapshot_missing'])
    if any(source.get('source_id') == snapshot.get('source_id') for source in analysis['sources']):
        return _blocked(analysis, raw_hash, ['ambiguous_snapshot_source_identity'])
    snapshot.update(records=[], content_sha256=_hash([]))
    try:
        metadata = _source_metadata(snapshot, analysis['data_kind'], cutoff)
        if not metadata['feature_eligible']:
            raise ValueError('snapshot_not_available_before_cutoff')
        if not snapshot['reference'].startswith('synthetic:'):
            raise ValueError('synthetic_snapshot_reference_required')
        expected_by_team = _coverage(manifest, snapshot, analysis, cutoff)
    except ValueError as error:
        return _blocked(analysis, raw_hash, [str(error)])
    _, context_records, _ = _collect(analysis, cutoff)
    target_ids = {leg['game_id'] for leg in analysis['legs']}
    targets = [r for r in context_records if r['kind'] == 'scheduled_game' and r['game_id'] in target_ids]
    target_pairs = {(frozenset((r['home_team_id'], r['away_team_id'])), _instant(r['scheduled_kickoff']).astimezone(EASTERN).date().isoformat())
                    for r in targets}
    seasons = {r['season'] for r in targets}
    if len(seasons) != 1:
        return _blocked(analysis, raw_hash, ['unique_target_season_unverified'])
    identities = Counter(row['game_id'] for _, row in rows)
    records, lineage, excluded = [], [], []
    for index, row in rows:
        reason = None
        if row['game_id'] in target_ids or (frozenset((row['home_team'], row['away_team'])), row['gameday']) in target_pairs:
            reason = 'target_game_excluded'
        elif identities[row['game_id']] != 1:
            reason = 'duplicate_game_identity'
        if reason:
            excluded.append(dict(csv_row=index, game_id=row['game_id'], reason=reason))
            continue
        proof = manifest['row_evidence'].get(row['game_id'])
        try:
            if not isinstance(proof, dict):
                raise ValueError('row_provenance_missing')
            record = _row_record(row, proof, snapshot, analysis, metadata, cutoff)
            if record['season'] not in seasons:
                raise ValueError('out_of_scope_season')
        except (ValueError, TypeError, KeyError, OverflowError):
            excluded.append(dict(csv_row=index, game_id=row['game_id'], reason='row_provenance_or_chronology_invalid'))
            continue
        records.append(record)
        lineage.append(dict(game_id=row['game_id'], csv_row=index, source_id=snapshot['source_id'],
                            source_version=snapshot['version'], started_at=proof['started_at'],
                            completed_at=proof['completed_at'], reference=proof['reference'], raw_snapshot_sha256=raw_hash))
    snapshot.update(records=records, content_sha256=_hash(records))
    analysis['sources'].append(snapshot)
    result = assess_nfl(analysis)
    completeness = {}
    for team in analysis['teams']:
        expected = expected_by_team.get(team)
        actual = {r['game_id'] for r in records if team in (r['home_team_id'], r['away_team_id'])}
        missing, unexpected = sorted(set(expected or []) - actual), sorted(actual - set(expected or []))
        status = 'UNVERIFIED' if expected is None else 'INCOMPLETE' if missing or unexpected else 'DECLARED_SET_MATCHED'
        completeness[team] = dict(status=status,
                                  missing_game_ids=missing, unexpected_game_ids=unexpected)
    for leg in result['legs']:
        target = next((r for r in targets if r['game_id'] == leg['game_id']), None)
        if target and any(completeness[t]['status'] != 'DECLARED_SET_MATCHED'
                          for t in (target['home_team_id'], target['away_team_id'])):
            leg['metrics'], leg['evidence_for'], leg['evidence_against'] = [], [], []
            leg['missing_data'].append('history_incomplete')
        elif any(c['status'] != 'DECLARED_SET_MATCHED' for c in completeness.values()):
            for metric in leg['metrics']:
                if metric['name'] == 'opponent_strength':
                    metric.update(status='MISSING', selected=None, opponent=None, source_ids=[], game_ids=[])
                    leg['missing_data'].append('opponent_strength_inventory_incomplete')
    result['historical_adapter'] = dict(
        status='SYNTHETIC_ONLY', raw_snapshot_sha256=hashlib.sha256(csv_text.encode()).hexdigest(),
        completeness=completeness, record_provenance=lineage, excluded=excluded, missing_evidence=[],
    )
    return result
