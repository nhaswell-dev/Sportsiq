"""Synthetic-only assessment tests; no real NFL statistics or network access."""

import importlib
import copy
import hashlib
import json
import unittest


def assess(payload):
    try:
        module = importlib.import_module('sportsiq.analysis.nfl')
    except ModuleNotFoundError as error:
        raise AssertionError('offline NFL assessment service is not implemented') from error
    return module.assess_nfl(payload)


def empty_fixture():
    return {
        'schema_version': 1,
        'data_kind': 'synthetic',
        'mode': 'historical',
        'analysis_cutoff': '2026-10-18T19:00:00Z',
        'teams': {'SYN-H': 'Synthetic Harbor', 'SYN-V': 'Synthetic Valley'},
        'legs': [{'leg_id': 'synthetic-leg', 'market_ticker': 'SYNTHETIC-NFL-H-V-H',
                  'side': 'yes', 'selected_team_id': 'SYN-H', 'game_id': 'synthetic-target'}],
        'sources': [],
    }


def seal(source):
    source['content_sha256'] = hashlib.sha256(json.dumps(
        source['records'], sort_keys=True, separators=(',', ':'), allow_nan=False,
    ).encode()).hexdigest()
    return source


def source(source_id, records, *, later=False):
    day = '2026-10-19' if later else '2026-10-17'
    return seal({
        'source_id': source_id, 'data_kind': 'synthetic',
        'provider': 'SportsIQ synthetic test author', 'reference': 'synthetic:' + source_id,
        'version': 'synthetic-v1', 'reliable': True,
        'reliability_evidence': 'synthetic: authored deterministic fixture',
        'license': {'status': 'approved', 'reference': 'synthetic: original test data',
                    'allowed_uses': ['analysis', 'display'], 'attribution': 'SportsIQ synthetic fixture'},
        'published_at': day + 'T12:00:00Z', 'revision_at': day + 'T12:00:00Z',
        'available_at': day + 'T12:01:00Z', 'retrieved_at': '2026-10-20T12:02:00Z',
        'availability_evidence': {'kind': 'synthetic', 'reference': 'synthetic: immutable test snapshot',
                                  'observed_at': day + 'T12:01:00Z'},
        'records': records,
    })


def full_fixture():
    data = empty_fixture()
    data['teams'].update({'SYN-O': 'Synthetic Oak', 'SYN-B': 'Synthetic Birch'})
    target = {'kind': 'scheduled_game', 'game_id': 'synthetic-target', 'season': 2026,
              'season_type': 'REG', 'home_team_id': 'SYN-H', 'away_team_id': 'SYN-V',
              'scheduled_kickoff': '2026-10-18T20:05:00Z', 'neutral_site': False}
    data['sources'] = [source('history', [target])]
    for i, (home, away, hp, ap) in enumerate([
        ('SYN-H', 'SYN-O', 28, 14), ('SYN-B', 'SYN-H', 21, 14),
        ('SYN-V', 'SYN-B', 10, 24), ('SYN-O', 'SYN-V', 14, 21), ('SYN-O', 'SYN-B', 17, 7),
    ], 1):
        data['sources'][0]['records'].append({
            'kind': 'game_result', 'game_id': 'synthetic-prior-' + str(i),
            'season': 2026, 'season_type': 'REG', 'home_team_id': home, 'away_team_id': away,
            'started_at': '2026-10-11T17:00:00Z', 'completed_at': '2026-10-11T20:00:00Z',
            'home_points': hp, 'away_points': ap, 'status': 'final', 'neutral_site': False,
        })
    seal(data['sources'][0])
    data['sources'].append(source('kickoff', [{
        'kind': 'kickoff_verification', 'game_id': 'synthetic-target',
        'actual_kickoff': '2026-10-18T20:05:18Z',
    }], later=True))
    return data


class AssessmentTests(unittest.TestCase):
    def test_missing_evidence_returns_insufficient_without_numerical_features(self):
        result = assess(empty_fixture())
        self.assertEqual(result['data_kind'], 'synthetic')
        leg = result['legs'][0]
        self.assertEqual(leg['assessment'], 'INSUFFICIENT_DATA')
        self.assertEqual(leg['metrics'], [])
        self.assertIn('target_schedule_unavailable', leg['missing_data'])
        self.assertEqual(leg['evidence_for'], [])
        self.assertEqual(leg['evidence_against'], [])

    def test_valid_synthetic_history_produces_sourced_descriptive_metrics(self):
        result = assess(full_fixture())
        leg = result['legs'][0]
        self.assertEqual(result['analysis_cutoff'], '2026-10-18T19:00:00+00:00')
        self.assertEqual(leg['assessment'], 'INSUFFICIENT_DATA')
        metrics = {m['name']: m for m in leg['metrics']}
        record = metrics['record']['selected']
        self.assertEqual((record['wins'], record['losses'], record['ties']), (1, 1, 0))
        self.assertEqual(record['games'], 2)
        self.assertEqual(metrics['home_away']['selected']['home']['wins'], 1)
        self.assertEqual(metrics['home_away']['selected']['away']['losses'], 1)
        self.assertEqual(metrics['points']['selected']['scored'], 42)
        self.assertEqual(metrics['points']['selected']['allowed'], 35)
        self.assertEqual(metrics['points']['selected']['scored_per_game'], 21.0)
        self.assertEqual(metrics['points']['selected']['allowed_per_game'], 17.5)
        self.assertEqual(metrics['opponent_strength']['selected']['mean_opponent_win_fraction'], 0.5)
        self.assertEqual(metrics['opponent_strength']['source_ids'], ['history'])
        self.assertTrue(leg['evidence_for'])
        self.assertIn('predictive_method_unvalidated', leg['missing_data'])
        self.assertIn('supplied validated games only', leg['coverage'])
        self.assertEqual(result['sources'][0]['content_sha256'], full_fixture()['sources'][0]['content_sha256'])
        self.assertEqual(leg['actual_kickoff'], '2026-10-18T20:05:18+00:00')
        self.assertEqual(leg['kickoff_source_ids'], ['kickoff'])

    def test_source_provenance_is_fail_closed(self):
        mutations = [
            lambda s: s.pop('license'),
            lambda s: s['license'].update(status='unknown'),
            lambda s: s['license'].update(allowed_uses=['display']),
            lambda s: s['license'].update(reference=''),
            lambda s: s.update(reliable=False),
            lambda s: s.update(reliability_evidence=''),
            lambda s: s.pop('availability_evidence'),
            lambda s: s['availability_evidence'].update(kind='asserted'),
            lambda s: s['availability_evidence'].update(reference=''),
            lambda s: s.update(version=''),
            lambda s: s.update(content_sha256='0' * 64),
            lambda s: s.update(published_at='2026-10-18T19:00:00Z'),
            lambda s: s.update(revision_at='2026-10-18T19:00:00Z'),
            lambda s: s.update(available_at='2026-10-18T19:00:00Z'),
            lambda s: s['availability_evidence'].update(observed_at='2026-10-18T19:00:00Z'),
            lambda s: s.update(retrieved_at='2026-10-16T00:00:00Z'),
            lambda s: s.update(revision_at='2026-10-17T12:00:00'),
            lambda s: s.update(data_kind='observed'),
            lambda s: s.update(extra='FUTURE_SECRET_VALUE'),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                fixture = full_fixture()
                mutation(fixture['sources'][0])
                result = assess(fixture)
                self.assertEqual(result['legs'][0]['metrics'], [])
                self.assertEqual(result['legs'][0]['assessment'], 'INSUFFICIENT_DATA')
                self.assertTrue(result['excluded'])
                self.assertNotIn('FUTURE_SECRET_VALUE', json.dumps(result))

    def test_duplicate_source_identity_never_chooses_a_winner(self):
        fixture = full_fixture()
        fixture['sources'].append(copy.deepcopy(fixture['sources'][0]))
        result = assess(fixture)
        self.assertEqual(result['legs'][0]['metrics'], [])
        self.assertIn('ambiguous_source_id', {e['reason'] for e in result['excluded']})

    def test_future_and_target_results_cannot_change_metrics(self):
        expected = assess(full_fixture())['legs'][0]['metrics']
        for timing in ('future', 'boundary', 'target'):
            fixture = full_fixture()
            record = copy.deepcopy(fixture['sources'][0]['records'][1])
            record.update(game_id='synthetic-target' if timing == 'target' else 'future-result', home_points=199)
            if timing != 'target':
                record['completed_at'] = '2026-10-18T19:00:00Z' if timing == 'boundary' else '2026-10-20T20:00:00Z'
            fixture['sources'].append(source('unavailable-result', [record], later=timing != 'target'))
            result = assess(fixture)
            self.assertEqual(result['legs'][0]['metrics'], expected)
            self.assertTrue(result['excluded'])
            self.assertNotIn('home_points', json.dumps(result))

    def test_unsupported_observations_are_quarantined_not_echoed(self):
        for kind in ('statistic', 'rating', 'roster_update', 'price'):
            fixture = full_fixture()
            fixture['sources'].append(source('unsupported', [{'kind': kind, 'value': 'FUTURE_VALUE_DO_NOT_ECHO'}]))
            result = assess(fixture)
            self.assertIn('unsupported_record_kind', {r['reason'] for r in result['excluded']})
            self.assertNotIn('FUTURE_VALUE_DO_NOT_ECHO', json.dumps(result))

    def test_invalid_result_records_are_excluded_without_guessing(self):
        mutations = [
            {'home_points': True}, {'away_points': -1}, {'home_points': 1.2},
            {'status': 'in_progress'}, {'completed_at': None},
            {'completed_at': '2026-10-11T20:00:00'},
            {'started_at': '2026-10-12T20:00:00Z'},
            {'completed_at': '2026-10-17T12:00:01Z'},
            {'away_team_id': 'SYN-H'}, {'home_team_id': 'unknown-team'},
            {'neutral_site': 'false'}, {'season': True}, {'season_type': 'POST'},
            {'rating': 'POST_CUTOFF_DO_NOT_ECHO'},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                fixture = full_fixture()
                fixture['sources'][0]['records'][1].update(mutation)
                seal(fixture['sources'][0])
                result = assess(fixture)
                self.assertTrue(result['excluded'])
                for metric in result['legs'][0]['metrics']:
                    self.assertNotIn('synthetic-prior-1', metric['game_ids'])
                self.assertNotIn('POST_CUTOFF_DO_NOT_ECHO', json.dumps(result))

    def test_duplicate_game_results_are_ambiguous_even_across_sources(self):
        fixture = full_fixture()
        fixture['sources'].append(source('duplicate-game', [copy.deepcopy(fixture['sources'][0]['records'][1])]))
        result = assess(fixture)
        self.assertIn('ambiguous_record_identity', {r['reason'] for r in result['excluded']})
        self.assertNotIn('synthetic-prior-1', result['legs'][0]['metrics'][0]['game_ids'])

    def test_cutoff_must_strictly_precede_scheduled_and_actual_kickoff(self):
        for field in ('scheduled_kickoff', 'actual_kickoff'):
            fixture = full_fixture()
            src = fixture['sources'][0 if field == 'scheduled_kickoff' else 1]
            src['records'][0][field] = fixture['analysis_cutoff']
            seal(src)
            leg = assess(fixture)['legs'][0]
            self.assertEqual(leg['metrics'], [])
            self.assertIn('cutoff_not_pregame', leg['missing_data'])

    def test_actual_kickoff_is_required_for_historical_not_prospective_report(self):
        fixture = full_fixture()
        fixture['sources'].pop()
        leg = assess(fixture)['legs'][0]
        self.assertEqual(leg['metrics'], [])
        self.assertIn('actual_kickoff_unverified', leg['missing_data'])
        fixture['mode'] = 'prospective'
        leg = assess(fixture)['legs'][0]
        self.assertTrue(leg['metrics'])
        self.assertIsNone(leg['actual_kickoff'])
        self.assertIn('actual_kickoff_unverified', leg['uncertainty'])

    def test_ambiguous_schedule_or_kickoff_is_not_silently_resolved(self):
        for index in (0, 1):
            fixture = full_fixture()
            fixture['sources'].append(source('conflicting-copy', [copy.deepcopy(fixture['sources'][index]['records'][0])],
                                               later=index == 1))
            self.assertEqual(assess(fixture)['legs'][0]['metrics'], [])

    def test_unsupported_side_and_wrong_selection_identity_are_not_inverted(self):
        for changes in ({'side': 'no'}, {'selected_team_id': 'SYN-O'}):
            fixture = full_fixture()
            fixture['legs'][0].update(changes)
            leg = assess(fixture)['legs'][0]
            self.assertEqual(leg['metrics'], [])
            self.assertEqual(leg['assessment'], 'INSUFFICIENT_DATA')
            self.assertIn('unsupported_or_conflicting_selection', leg['missing_data'])

    def test_top_level_shape_and_naive_cutoff_are_rejected(self):
        mutations = [lambda f: f.update(analysis_cutoff='2026-10-18T19:00:00'),
                     lambda f: f.update(schema_version=True), lambda f: f.update(data_kind='unknown'),
                     lambda f: f.update(mode='final'), lambda f: f.update(legs=[]),
                     lambda f: f['legs'].append(copy.deepcopy(f['legs'][0])),
                     lambda f: f['legs'][0].update(rating='avoid'),
                     lambda f: f.update(sources=None), lambda f: f.update(price=0.5)]
        for mutation in mutations:
            fixture = full_fixture()
            mutation(fixture)
            with self.assertRaises(ValueError):
                assess(fixture)

    def test_ties_neutral_venues_and_zero_game_opponents_are_explicit(self):
        fixture = full_fixture()
        fixture['sources'][0]['records'][1].update(home_points=14, neutral_site=True)
        seal(fixture['sources'][0])
        metrics = {m['name']: m for m in assess(fixture)['legs'][0]['metrics']}
        self.assertEqual(metrics['record']['selected']['ties'], 1)
        self.assertEqual(metrics['home_away']['selected']['neutral']['games'], 1)
        self.assertIsNone(metrics['home_away']['selected']['home']['win_fraction'])
        fixture['sources'][0]['records'] = fixture['sources'][0]['records'][:3]
        seal(fixture['sources'][0])
        metrics = {m['name']: m for m in assess(fixture)['legs'][0]['metrics']}
        self.assertIsNone(metrics['opponent_strength']['selected']['mean_opponent_win_fraction'])
        self.assertEqual(metrics['opponent_strength']['selected']['opponents_observed'], 0)
        self.assertEqual(metrics['opponent_strength']['status'], 'MISSING')

    def test_post_cutoff_correction_cannot_replace_pre_cutoff_snapshot(self):
        fixture = full_fixture()
        baseline = assess(fixture)['legs'][0]['metrics']
        correction = copy.deepcopy(fixture['sources'][0]['records'][1])
        correction['home_points'] = 199
        fixture['sources'].append(source('later-correction', [correction], later=True))
        result = assess(fixture)
        self.assertEqual(result['legs'][0]['metrics'], baseline)
        self.assertNotIn('later-correction', {s['source_id'] for s in result['sources']})

    def test_offset_cutoff_normalization_and_input_immutability(self):
        fixture = full_fixture()
        fixture['analysis_cutoff'] = '2026-10-18T15:00:00-04:00'
        original = copy.deepcopy(fixture)
        result = assess(fixture)
        self.assertEqual(result['analysis_cutoff'], '2026-10-18T19:00:00+00:00')
        self.assertEqual(fixture, original)
        self.assertTrue(result['legs'][0]['metrics'])

    def test_prospective_report_cannot_ignore_conflicting_actual_kickoffs(self):
        fixture = full_fixture()
        fixture['mode'] = 'prospective'
        conflicting = copy.deepcopy(fixture['sources'][1]['records'][0])
        conflicting['actual_kickoff'] = '2026-10-18T18:59:00Z'
        fixture['sources'].append(source('conflicting-kickoff', [conflicting], later=True))
        leg = assess(fixture)['legs'][0]
        self.assertEqual(leg['metrics'], [])
        self.assertIn('actual_kickoff_ambiguous', leg['missing_data'])

    def test_partial_opponent_strength_is_not_labeled_fully_available(self):
        fixture = full_fixture()
        fixture['sources'][0]['records'] = fixture['sources'][0]['records'][:4]
        seal(fixture['sources'][0])
        strength = assess(fixture)['legs'][0]['metrics'][3]
        self.assertEqual(strength['status'], 'PARTIAL')
        self.assertEqual(strength['selected']['missing_opponents'], ['SYN-O'])

    def test_worse_history_creates_opposing_evidence_not_an_avoid_rating(self):
        fixture = full_fixture()
        fixture['sources'][0]['records'][1].update(home_points=0)
        seal(fixture['sources'][0])
        leg = assess(fixture)['legs'][0]
        self.assertTrue(leg['evidence_against'])
        self.assertEqual(leg['assessment'], 'INSUFFICIENT_DATA')
        self.assertNotIn('rating', leg)

    def test_malformed_nested_source_records_are_reported_as_unavailable(self):
        for malformed in (None, [], 'not-a-record', {'kind': [], 'game_id': 'bad'}):
            fixture = full_fixture()
            fixture['sources'][0]['records'].append(malformed)
            seal(fixture['sources'][0])
            self.assertTrue(assess(fixture)['excluded'])

    def test_out_of_range_timestamp_is_quarantined_without_discarding_good_history(self):
        for field, value in (('started_at', '0001-01-01T00:00:00+01:00'),
                             ('completed_at', '9999-12-31T23:59:59-01:00')):
            fixture = full_fixture()
            fixture['sources'][0]['records'][1][field] = value
            seal(fixture['sources'][0])
            result = assess(fixture)
            self.assertIn('invalid_record', {row['reason'] for row in result['excluded']})
            self.assertTrue(result['legs'][0]['metrics'])
            self.assertNotIn('synthetic-prior-1', result['legs'][0]['metrics'][0]['game_ids'])
