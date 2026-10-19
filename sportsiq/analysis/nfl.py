"""Pure, fixture-first NFL descriptive assessment; no providers or prediction model."""

from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json


SOURCE_FIELDS = {
    'source_id', 'data_kind', 'provider', 'reference', 'version', 'reliable',
    'reliability_evidence', 'license', 'published_at', 'revision_at', 'available_at',
    'retrieved_at', 'availability_evidence', 'content_sha256', 'records',
}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _source_metadata(source, data_kind, cutoff):
    """Check fixture attestations, not external legal authority or archive authenticity."""
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
        raise ValueError('invalid_source_schema')
    if not all(_text(source[k]) for k in ('source_id', 'provider', 'reference', 'version', 'reliability_evidence')):
        raise ValueError('missing_source_provenance')
    if source['data_kind'] != data_kind or source['reliable'] is not True:
        raise ValueError('unreliable_or_mislabeled_source')
    license_info = source['license']
    if (not isinstance(license_info, dict)
            or set(license_info) != {'status', 'reference', 'allowed_uses', 'attribution'}
            or license_info['status'] != 'approved'
            or not all(_text(license_info[k]) for k in ('reference', 'attribution'))
            or not isinstance(license_info['allowed_uses'], list)
            or not all(_text(v) for v in license_info['allowed_uses'])
            or not {'analysis', 'display'} <= set(license_info['allowed_uses'])):
        raise ValueError('unlicensed_for_analysis_and_display')
    evidence = source['availability_evidence']
    if (not isinstance(evidence, dict) or set(evidence) != {'kind', 'reference', 'observed_at'}
            or not _text(evidence['reference'])):
        raise ValueError('availability_evidence_missing')
    kinds = ('synthetic',) if data_kind == 'synthetic' else ('archive', 'capture')
    if evidence['kind'] not in kinds:
        raise ValueError('availability_evidence_unsupported')
    if data_kind != 'synthetic' and any('synthetic:' in text.lower() for text in (
            source['reference'], license_info['reference'], evidence['reference'])):
        raise ValueError('synthetic_provenance_mismatch')
    if not isinstance(source['records'], list) or len(source['records']) > 10000:
        raise ValueError('invalid_source_records')
    try:
        digest = hashlib.sha256(json.dumps(source['records'], sort_keys=True, separators=(',', ':'),
                                          allow_nan=False).encode()).hexdigest()
        timestamps = [_instant(source[k]) for k in ('published_at', 'revision_at', 'available_at')]
        observed, retrieved = _instant(evidence['observed_at']), _instant(source['retrieved_at'])
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError('invalid_source_timestamps_or_content') from None
    if source['content_sha256'] != digest:
        raise ValueError('snapshot_hash_mismatch')
    if timestamps != sorted(timestamps) or not timestamps[-1] <= observed <= retrieved:
        raise ValueError('source_timestamp_conflict')
    if evidence['kind'] == 'capture' and observed != retrieved:
        raise ValueError('capture_time_conflict')
    metadata = {k: deepcopy(v) for k, v in source.items() if k != 'records'}
    metadata['feature_eligible'] = all(t < cutoff for t in timestamps + [observed])
    return metadata


def _collect(payload, cutoff):
    sources, records, excluded = [], [], []
    ids = Counter(s['source_id'] for s in payload['sources']
                  if isinstance(s, dict) and _text(s.get('source_id')))
    for source in payload['sources']:
        sid = source.get('source_id') if isinstance(source, dict) and _text(source.get('source_id')) else None
        try:
            if sid and ids[sid] != 1:
                raise ValueError('ambiguous_source_id')
            metadata = _source_metadata(source, payload['data_kind'], cutoff)
        except ValueError as error:
            excluded.append({'source_id': sid, 'reason': str(error)})
            continue
        retained = False
        for record in source['records']:
            try:
                _validate_record(record, payload, metadata, cutoff)
            except (ValueError, TypeError, KeyError):
                # Reason codes are generated locally; never echo unsupported values.
                reason = 'invalid_record'
                if isinstance(record, dict) and record.get('kind') not in (
                        'scheduled_game', 'game_result', 'kickoff_verification'):
                    reason = 'unsupported_record_kind'
                elif isinstance(record, dict) and record.get('kind') != 'kickoff_verification' and not metadata['feature_eligible']:
                    reason = 'source_not_available_before_cutoff'
                excluded.append({'source_id': sid, 'reason': reason})
                continue
            records.append({**record, '_source_id': sid})
            retained = True
        if retained:
            sources.append(metadata)
    identities = Counter((r['kind'], r['game_id']) for r in records)
    unique = []
    for record in records:
        if identities[(record['kind'], record['game_id'])] != 1:
            excluded.append({'source_id': record['_source_id'], 'reason': 'ambiguous_record_identity',
                             'kind': record['kind'], 'game_id': record['game_id']})
        else:
            unique.append(record)
    return sources, unique, excluded


def _validate_record(record, payload, metadata, cutoff):
    if not isinstance(record, dict) or not _text(record.get('game_id')):
        raise ValueError('invalid_record')
    kind = record.get('kind')
    if kind == 'kickoff_verification':
        if set(record) != {'kind', 'game_id', 'actual_kickoff'}:
            raise ValueError('invalid_kickoff_record')
        if _instant(record['actual_kickoff']) > _instant(metadata['revision_at']):
            raise ValueError('kickoff_observation_before_event')
        return
    if not metadata['feature_eligible']:
        raise ValueError('source_not_available_before_cutoff')
    common = {'kind', 'game_id', 'season', 'season_type', 'home_team_id', 'away_team_id', 'neutral_site'}
    fields = {
        'scheduled_game': {'scheduled_kickoff'},
        'game_result': {'started_at', 'completed_at', 'status', 'home_points', 'away_points'},
    }
    if not isinstance(kind, str) or kind not in fields or set(record) != common | fields[kind]:
        raise ValueError('unsupported_or_invalid_record_fields')
    if (type(record['season']) is not int or not 1920 <= record['season'] <= 3000
            or record['season_type'] != 'REG' or type(record['neutral_site']) is not bool
            or not all(_text(record[k]) and record[k] in payload['teams'] for k in ('home_team_id', 'away_team_id'))
            or record['home_team_id'] == record['away_team_id']):
        raise ValueError('invalid_game_identity_or_scope')
    if kind == 'scheduled_game':
        _instant(record['scheduled_kickoff'])
        return
    if (record['game_id'] in {leg['game_id'] for leg in payload['legs']}
            or record['status'] != 'final'
            or not all(type(record[k]) is int and 0 <= record[k] <= 200 for k in ('home_points', 'away_points'))):
        raise ValueError('ineligible_result')
    started, completed = _instant(record['started_at']), _instant(record['completed_at'])
    if not started < completed < cutoff or completed > _instant(metadata['revision_at']):
        raise ValueError('ineligible_result_time')


def _instant(value):
    if not isinstance(value, str):
        raise ValueError('timezone-aware timestamp required')
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('timezone-aware timestamp required')
    try:
        return instant.astimezone(timezone.utc)
    except OverflowError:
        raise ValueError('timestamp outside UTC range') from None


def _validate_input(payload):
    fields = {'schema_version', 'data_kind', 'mode', 'analysis_cutoff', 'teams', 'legs', 'sources'}
    if (not isinstance(payload, dict) or set(payload) != fields
            or type(payload['schema_version']) is not int or payload['schema_version'] != 1
            or payload['data_kind'] not in ('synthetic', 'observed')
            or payload['mode'] not in ('historical', 'prospective')
            or not isinstance(payload['teams'], dict) or not payload['teams']
            or not all(_text(k) and _text(v) for k, v in payload['teams'].items())
            or not isinstance(payload['sources'], list) or len(payload['sources']) > 100
            or not isinstance(payload['legs'], list) or not 1 <= len(payload['legs']) <= 100):
        raise ValueError('invalid NFL analysis fixture')
    _instant(payload['analysis_cutoff'])
    leg_fields = {'leg_id', 'market_ticker', 'side', 'selected_team_id', 'game_id'}
    for leg in payload['legs']:
        if not isinstance(leg, dict) or set(leg) != leg_fields or not all(_text(v) for v in leg.values()):
            raise ValueError('invalid NFL analysis leg')
    for key in ('leg_id', 'market_ticker', 'game_id'):
        if len({leg[key] for leg in payload['legs']}) != len(payload['legs']):
            raise ValueError('duplicate NFL analysis leg identity')


def _scores(game, team):
    if game['home_team_id'] == team:
        return game['home_points'], game['away_points']
    return game['away_points'], game['home_points']


def _record(games, team):
    scores = [_scores(game, team) for game in games]
    wins = sum(scored > allowed for scored, allowed in scores)
    ties = sum(scored == allowed for scored, allowed in scores)
    return {
        'games': len(games), 'wins': wins, 'losses': len(games) - wins - ties, 'ties': ties,
        'win_fraction': round((wins + ties / 2) / len(games), 6) if games else None,
    }


def _team_metrics(games, team):
    history = [g for g in games if team in (g['home_team_id'], g['away_team_id'])]
    splits = {
        venue: _record([g for g in history if (
            'neutral' if g['neutral_site'] else 'home' if g['home_team_id'] == team else 'away'
        ) == venue], team) for venue in ('home', 'away', 'neutral')
    }
    scored = sum(_scores(g, team)[0] for g in history)
    allowed = sum(_scores(g, team)[1] for g in history)
    opponents = sorted({g['away_team_id'] if g['home_team_id'] == team else g['home_team_id'] for g in history})
    opponent_records, strength_games = {}, []
    for opponent in opponents:
        observed = [g for g in games if opponent in (g['home_team_id'], g['away_team_id'])
                    and team not in (g['home_team_id'], g['away_team_id'])]
        strength_games.extend(observed)
        opponent_records[opponent] = _record(observed, opponent)
    fractions = [r['win_fraction'] for r in opponent_records.values() if r['games']]
    values = {
        'record': _record(history, team), 'home_away': splits,
        'points': {'games': len(history), 'scored': scored, 'allowed': allowed,
                   'scored_per_game': round(scored / len(history), 6) if history else None,
                   'allowed_per_game': round(allowed / len(history), 6) if history else None},
        'opponent_strength': {
            'mean_opponent_win_fraction': round(sum(fractions) / len(fractions), 6) if fractions else None,
            'opponents_observed': len(fractions), 'opponents_total': len(opponents),
            'missing_opponents': [t for t, r in opponent_records.items() if not r['games']],
            'opponent_records': opponent_records,
        },
    }
    return values, history, strength_games


def _describe(leg, games, selected, opponent):
    left, left_games, left_strength = _team_metrics(games, selected)
    right, right_games, right_strength = _team_metrics(games, opponent)
    for name in left:
        used = left_games + right_games
        if name == 'opponent_strength':
            used += left_strength + right_strength
        present = bool(left_games and right_games)
        status = 'AVAILABLE' if present else 'MISSING'
        if name == 'opponent_strength':
            present = present and bool(left[name]['opponents_observed'] and right[name]['opponents_observed'])
            status = 'MISSING' if not present else 'PARTIAL' if (
                left[name]['missing_opponents'] or right[name]['missing_opponents']
            ) else 'AVAILABLE'
        leg['metrics'].append({
            'name': name, 'status': status,
            'selected': left[name] if left_games else None,
            'opponent': right[name] if right_games else None,
            'source_ids': sorted({g['_source_id'] for g in used}),
            'game_ids': sorted({g['game_id'] for g in used}),
        })
        if not present:
            leg['missing_data'].append(name + '_unavailable')
        elif status == 'PARTIAL':
            leg['missing_data'].append(name + '_incomplete')
    if left_games and right_games:
        comparisons = [
            ('record', left['record']['win_fraction'], right['record']['win_fraction'], True),
            ('points_scored_per_game', left['points']['scored_per_game'], right['points']['scored_per_game'], True),
            ('points_allowed_per_game', left['points']['allowed_per_game'], right['points']['allowed_per_game'], False),
        ]
        for name, a, b, higher in comparisons:
            if a != b:
                direction = 'evidence_for' if (a > b) == higher else 'evidence_against'
                leg[direction].append(f'{name}: selected={a}, opponent={b}; supplied-history comparison only')


def assess_nfl(payload):
    """Describe supplied evidence only; never issue a predictive selection rating."""
    _validate_input(payload)
    cutoff = _instant(payload['analysis_cutoff'])
    sources, records, excluded = _collect(payload, cutoff)
    result = {
        'schema_version': 1, 'data_kind': payload['data_kind'], 'mode': payload['mode'],
        'analysis_cutoff': cutoff.isoformat(),
        'notice': 'SYNTHETIC DATA - NOT ACTUAL NFL STATISTICS' if payload['data_kind'] == 'synthetic'
                  else 'Offline fixture assertions; external provenance is not independently authenticated',
        'sources': sources, 'excluded': excluded, 'legs': [],
    }
    target_ids = {leg['game_id'] for leg in payload['legs']}
    for selection in payload['legs']:
        leg = {
            **selection, 'analysis_cutoff': cutoff.isoformat(),
            'assessment': 'INSUFFICIENT_DATA',
            'coverage': 'supplied validated games only; full season coverage unverified',
            'scheduled_kickoff': None, 'actual_kickoff': None,
            'schedule_source_ids': [], 'kickoff_source_ids': [], 'metrics': [],
            'missing_data': ['predictive_method_unvalidated', 'full_season_coverage_unverified'],
            'evidence_for': [],
            'evidence_against': [],
            'uncertainty': ['No validated predictive method; comparisons are not winning probabilities',
                            'Injuries, rosters, ratings and prices are not supported inputs'],
        }
        if excluded:
            leg['uncertainty'].append('Some supplied evidence was rejected; history may be incomplete')
        schedules = [r for r in records if r['kind'] == 'scheduled_game' and r['game_id'] == selection['game_id']]
        if len(schedules) == 1:
            target = schedules[0]
            leg['scheduled_kickoff'] = _instant(target['scheduled_kickoff']).isoformat()
            leg['schedule_source_ids'] = [target['_source_id']]
            kickoffs = [r for r in records if r['kind'] == 'kickoff_verification' and r['game_id'] == selection['game_id']]
            if len(kickoffs) == 1:
                leg['actual_kickoff'] = _instant(kickoffs[0]['actual_kickoff']).isoformat()
                leg['kickoff_source_ids'] = [kickoffs[0]['_source_id']]
            if any(e.get('kind') == 'kickoff_verification' and e.get('game_id') == selection['game_id']
                   for e in excluded):
                leg['missing_data'].append('actual_kickoff_ambiguous')
                result['legs'].append(leg)
                continue
            selected = selection['selected_team_id']
            if selection['side'] != 'yes' or selected not in (target['home_team_id'], target['away_team_id']):
                leg['missing_data'].append('unsupported_or_conflicting_selection')
                result['legs'].append(leg)
                continue
            if cutoff >= _instant(target['scheduled_kickoff']) or (
                    leg['actual_kickoff'] is not None and cutoff >= _instant(leg['actual_kickoff'])):
                leg['missing_data'].append('cutoff_not_pregame')
                result['legs'].append(leg)
                continue
            if leg['actual_kickoff'] is None:
                if payload['mode'] == 'historical':
                    leg['missing_data'].append('actual_kickoff_unverified')
                    result['legs'].append(leg)
                    continue
                leg['uncertainty'].append('actual_kickoff_unverified')
            opponent = target['away_team_id'] if selected == target['home_team_id'] else target['home_team_id']
            leg['selected_team'] = payload['teams'][selected]
            leg['opponent_team'] = payload['teams'][opponent]
            leg['selected_venue'] = 'neutral' if target['neutral_site'] else 'home' if selected == target['home_team_id'] else 'away'
            games = [r for r in records if r['kind'] == 'game_result' and r['game_id'] not in target_ids
                     and r['season'] == target['season'] and r['season_type'] == 'REG'
                     and _instant(r['completed_at']) < cutoff]
            _describe(leg, games, selected, opponent)
        else:
            leg['missing_data'].append('target_schedule_unavailable')
        result['legs'].append(leg)
    return result
