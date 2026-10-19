"""Original synthetic CSV tests, including actual target identities but no real statistics."""

import copy
import csv
import hashlib
import importlib
import io
import json
import unittest

from test_nfl_assessment import source

HEADER = 'game_id,season,game_type,gameday,gametime,home_team,away_team,home_score,away_score'


def adapt(text, manifest):
    try:
        module = importlib.import_module('sportsiq.providers.nfl_history')
    except ModuleNotFoundError as error:
        raise AssertionError('offline historical CSV adapter not implemented') from error
    return module.assess_history(text, manifest)


def example():
    text = HEADER + '\n' + '\n'.join([
        'syn-la,2026,REG,2026-10-11,13:00,LA,ARI,24,10',
        'syn-sf,2026,REG,2026-10-12,20:15,SF,WAS,14,21',
    ]) + '\n'
    schedules = [
        dict(kind='scheduled_game', game_id='2026_06_ARI_LA', season=2026, season_type='REG',
             home_team_id='LA', away_team_id='ARI', neutral_site=False, scheduled_kickoff='2026-10-18T20:05:00Z'),
        dict(kind='scheduled_game', game_id='2026_06_WAS_SF', season=2026, season_type='REG',
             home_team_id='SF', away_team_id='WAS', neutral_site=False, scheduled_kickoff='2026-10-20T00:15:00Z'),
    ]
    snapshot = source('synthetic-history', [])
    snapshot.pop('records')
    snapshot.pop('content_sha256')
    manifest = {
        'schema_version': 1,
        'analysis': dict(schema_version=1, data_kind='synthetic', mode='prospective',
                         analysis_cutoff='2026-10-18T19:00:00Z',
                         teams={t: n + ' (SYNTHETIC STATISTICS)' for t, n in {
                             'LA': 'Los Angeles Rams', 'ARI': 'Arizona Cardinals',
                             'SF': 'San Francisco 49ers', 'WAS': 'Washington Commanders'}.items()},
                         legs=[dict(leg_id='rams', game_id='2026_06_ARI_LA',
                                    market_ticker='KXNFLGAME-26OCT18ARILAR-LAR', side='yes', selected_team_id='LA'),
                               dict(leg_id='49ers', game_id='2026_06_WAS_SF',
                                    market_ticker='KXNFLGAME-26OCT19WASSF-SF', side='yes', selected_team_id='SF')],
                         sources=[source('synthetic-schedule', schedules)]),
        'snapshot': snapshot,
        'raw_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'row_evidence': {
            'syn-la': dict(source_version='synthetic-v1', reference='synthetic:row-la',
                           started_at='2026-10-11T17:01:00Z', completed_at='2026-10-11T20:00:00Z',
                           status='final', neutral_site=False),
            'syn-sf': dict(source_version='synthetic-v1', reference='synthetic:row-sf',
                           started_at='2026-10-13T00:15:23Z', completed_at='2026-10-13T03:20:00Z',
                           status='final', neutral_site=False),
        },
        'coverage': dict(source_version='synthetic-v1', as_of='2026-10-18T19:00:00Z',
                         expected_game_ids={'LA': ['syn-la'], 'ARI': ['syn-la'], 'SF': ['syn-sf'], 'WAS': ['syn-sf']}),
    }
    return text, manifest


def resign(text, manifest):
    manifest['raw_sha256'] = hashlib.sha256(text.encode()).hexdigest()


class NFLHistoryTests(unittest.TestCase):
    def test_both_target_matchups_have_sourced_synthetic_prior_game_metrics(self):
        text, manifest = example()
        result = adapt(text, manifest)
        self.assertIn('SYNTHETIC', result['notice'])
        self.assertEqual(result['historical_adapter']['status'], 'SYNTHETIC_ONLY')
        self.assertEqual(len(result['legs']), 2)
        rams, niners = result['legs']
        self.assertEqual(rams['market_ticker'], 'KXNFLGAME-26OCT18ARILAR-LAR')
        self.assertEqual(niners['market_ticker'], 'KXNFLGAME-26OCT19WASSF-SF')
        rm = {m['name']: m for m in rams['metrics']}
        nm = {m['name']: m for m in niners['metrics']}
        self.assertEqual(rm['record']['selected']['wins'], 1)
        self.assertEqual(nm['record']['selected']['losses'], 1)
        self.assertEqual(rm['points']['selected']['scored'], 24)
        self.assertEqual(nm['points']['selected']['allowed'], 21)
        self.assertEqual(rm['home_away']['selected']['home']['wins'], 1)
        self.assertEqual(result['historical_adapter']['completeness']['LA']['status'], 'DECLARED_SET_MATCHED')
        self.assertEqual(result['historical_adapter']['record_provenance'][0]['csv_row'], 2)
        self.assertEqual(result['historical_adapter']['raw_snapshot_sha256'], manifest['raw_sha256'])
        self.assertTrue(all(l['assessment'] == 'INSUFFICIENT_DATA' for l in result['legs']))

    def test_snapshot_permission_and_publication_gates_fail_closed(self):
        for mutation in (
            lambda m: m['snapshot']['license'].update(status='unknown'),
            lambda m: m['snapshot'].update(reliable=False),
            lambda m: m['snapshot'].pop('availability_evidence'),
            lambda m: m['snapshot'].update(revision_at='2026-10-19T00:00:00Z'),
            lambda m: m['snapshot'].update(available_at='2026-10-18T19:00:00Z'),
            lambda m: m.update(raw_sha256='0' * 64),
            lambda m: m.update(snapshot=None),
        ):
            text, manifest = example()
            mutation(manifest)
            result = adapt(text, manifest)
            self.assertEqual(result['historical_adapter']['status'], 'BLOCKED')
            self.assertTrue(result['historical_adapter']['missing_evidence'])
            self.assertTrue(all(not leg['metrics'] for leg in result['legs']))

    def test_self_asserted_observed_license_cannot_enable_unapproved_real_source(self):
        text, manifest = example()
        manifest['analysis']['data_kind'] = 'observed'
        result = adapt(text, manifest)
        self.assertEqual(result['historical_adapter']['status'], 'BLOCKED')
        self.assertIn('real_dataset_not_approved', result['historical_adapter']['missing_evidence'])
        self.assertTrue(all(not leg['metrics'] and leg['assessment'] == 'INSUFFICIENT_DATA' for leg in result['legs']))
        self.assertNotIn('home_points', json.dumps(result))

    def test_both_targets_are_excluded_before_any_result_score_is_parsed(self):
        text, manifest = example()
        baseline = adapt(text, manifest)['legs']
        text += ('2026_06_ARI_LA,2026,REG,2026-10-18,16:05,LA,ARI,TARGET_RESULT,10\n'
                 '2026_06_WAS_SF,2026,REG,2026-10-19,20:15,SF,WAS,TARGET_RESULT,10\n'
                 'disguised-target,2026,REG,2026-10-18,16:05,LA,ARI,TARGET_RESULT,10\n')
        resign(text, manifest)
        result = adapt(text, manifest)
        self.assertEqual([l['metrics'] for l in result['legs']], [l['metrics'] for l in baseline])
        self.assertEqual(len(result['historical_adapter']['excluded']), 3)
        self.assertNotIn('TARGET_RESULT', json.dumps(result))

    def test_row_cutoff_completion_status_date_and_version_are_validated(self):
        mutations = [
            lambda p: p.update(completed_at='2026-10-18T19:00:00Z'),
            lambda p: p.update(completed_at='2026-10-20T23:00:00Z'),
            lambda p: p.update(completed_at=None),
            lambda p: p.update(started_at='2026-10-12T17:00:00Z'),
            lambda p: p.update(started_at='2026-10-11T17:00:00'),
            lambda p: p.update(source_version='post-cutoff-revision'),
            lambda p: p.update(reference=''),
            lambda p: p.update(status='in_progress'),
        ]
        for mutation in mutations:
            text, manifest = example()
            mutation(manifest['row_evidence']['syn-la'])
            result = adapt(text, manifest)
            self.assertEqual(result['legs'][0]['metrics'], [])
            self.assertIn('history_incomplete', result['legs'][0]['missing_data'])
            self.assertTrue(result['legs'][1]['metrics'])
            self.assertTrue(result['historical_adapter']['excluded'])

    def test_no_completion_or_neutral_site_information_is_invented(self):
        text, manifest = example()
        manifest['row_evidence'].pop('syn-la')
        result = adapt(text, manifest)
        self.assertEqual(result['legs'][0]['metrics'], [])
        self.assertIn('syn-la', result['historical_adapter']['completeness']['LA']['missing_game_ids'])

    def test_completeness_inventory_mismatch_withholds_affected_leg(self):
        text, manifest = example()
        manifest['coverage']['expected_game_ids']['LA'].append('missing-prior-game')
        result = adapt(text, manifest)
        self.assertEqual(result['legs'][0]['metrics'], [])
        self.assertTrue(result['legs'][1]['metrics'])
        self.assertEqual(result['historical_adapter']['completeness']['LA']['missing_game_ids'], ['missing-prior-game'])

    def test_coverage_manifest_requires_cutoff_and_snapshot_version_match(self):
        for changes in ({'as_of': '2026-10-19T23:00:00Z'}, {'source_version': 'later-version'}):
            text, manifest = example()
            manifest['coverage'].update(changes)
            result = adapt(text, manifest)
            self.assertEqual(result['historical_adapter']['status'], 'BLOCKED')
            self.assertTrue(all(not leg['metrics'] for leg in result['legs']))

    def test_duplicate_game_rows_cannot_count_twice_or_hide_missing_data(self):
        text, manifest = example()
        text += text.splitlines()[1] + '\n'
        resign(text, manifest)
        result = adapt(text, manifest)
        self.assertEqual(result['legs'][0]['metrics'], [])
        self.assertIn('duplicate_game_identity', {r['reason'] for r in result['historical_adapter']['excluded']})

    def test_same_day_prior_result_requires_explicit_eligible_completion(self):
        text, manifest = example()
        text = text.replace('syn-la,2026,REG,2026-10-11', 'syn-la,2026,REG,2026-10-18')
        manifest['row_evidence']['syn-la'].update(started_at='2026-10-18T17:00:00Z', completed_at='2026-10-18T18:00:00Z')
        manifest['snapshot'].update(revision_at='2026-10-18T18:10:00Z', available_at='2026-10-18T18:11:00Z')
        manifest['snapshot']['availability_evidence']['observed_at'] = '2026-10-18T18:11:00Z'
        # Use a distinct prior opponent pair so this is not a disguised target.
        text = text.replace('13:00,LA,ARI,24', '13:00,LA,WAS,24')
        manifest['coverage']['expected_game_ids']['ARI'] = []
        manifest['coverage']['expected_game_ids']['WAS'].append('syn-la')
        resign(text, manifest)
        result = adapt(text, manifest)
        self.assertIn('syn-la', [r['game_id'] for r in result['historical_adapter']['record_provenance']])

    def test_analysis_sources_cannot_smuggle_precomputed_history(self):
        text, manifest = example()
        manifest['analysis']['sources'][0]['records'].append(dict(kind='game_result', home_points=199))
        result = adapt(text, manifest)
        self.assertEqual(result['historical_adapter']['status'], 'BLOCKED')
        self.assertTrue(all(not leg['metrics'] for leg in result['legs']))

    def test_snapshot_cannot_reuse_an_existing_source_identity(self):
        text, manifest = example()
        manifest['snapshot']['source_id'] = manifest['analysis']['sources'][0]['source_id']
        result = adapt(text, manifest)
        self.assertEqual(result['historical_adapter']['status'], 'BLOCKED')
        self.assertTrue(all(not leg['metrics'] for leg in result['legs']))

    def test_reversed_target_pair_still_cannot_become_prior_history(self):
        text, manifest = example()
        text += 'disguised-reverse,2026,REG,2026-10-18,16:05,ARI,LA,TARGET_RESULT,10\n'
        resign(text, manifest)
        excluded = adapt(text, manifest)['historical_adapter']['excluded']
        self.assertEqual(excluded[-1]['reason'], 'target_game_excluded')

    def test_actual_start_before_csv_scheduled_start_is_conflicting_evidence(self):
        text, manifest = example()
        text = text.replace('2026-10-11,13:00', '2026-10-11,23:00')
        resign(text, manifest)
        result = adapt(text, manifest)
        self.assertEqual(result['legs'][0]['metrics'], [])
        self.assertTrue(result['historical_adapter']['excluded'])

    def test_row_order_does_not_change_metrics_and_missing_inventory_is_explicit(self):
        text, manifest = example()
        before = adapt(text, manifest)
        text = '\n'.join([text.splitlines()[0]] + list(reversed(text.splitlines()[1:]))) + '\n'
        resign(text, manifest)
        after = adapt(text, manifest)
        self.assertEqual([l['metrics'] for l in before['legs']], [l['metrics'] for l in after['legs']])
        manifest['coverage']['expected_game_ids'].pop('LA')
        result = adapt(text, manifest)
        self.assertEqual(result['legs'][0]['metrics'], [])
        self.assertEqual(result['historical_adapter']['completeness']['LA']['status'], 'UNVERIFIED')

    def test_ambiguous_csv_headers_and_unsupported_revision_fields_are_rejected(self):
        text, manifest = example()
        for extra in ('home_score', 'revision_at'):
            malformed = '\n'.join(line + ',' + extra if i == 0 else line + ',2026-10-20'
                                  for i, line in enumerate(text.splitlines())) + '\n'
            resign(malformed, manifest)
            with self.assertRaises(ValueError):
                adapt(malformed, manifest)

    def test_past_season_results_cannot_be_relabeled_as_the_target_season(self):
        text, manifest = example()
        text = text.replace('syn-la,2026,REG,2026-10-11', 'syn-la,2026,REG,2025-10-11')
        manifest['row_evidence']['syn-la'].update(
            started_at='2025-10-11T17:01:00Z', completed_at='2025-10-11T20:00:00Z')
        resign(text, manifest)
        result = adapt(text, manifest)
        self.assertEqual(result['legs'][0]['metrics'], [])
        self.assertIn('history_incomplete', result['legs'][0]['missing_data'])
        self.assertTrue(result['legs'][1]['metrics'])

    def test_january_regular_season_game_belongs_to_the_previous_season(self):
        text, manifest = example()
        text = text.replace('syn-la,2026,REG,2026-10-11', 'syn-la,2026,REG,2026-01-11')
        manifest['row_evidence']['syn-la'].update(
            started_at='2026-01-11T18:01:00Z', completed_at='2026-01-11T21:00:00Z')
        resign(text, manifest)
        self.assertEqual(adapt(text, manifest)['legs'][0]['metrics'], [])

    def test_csv_lineage_preserves_physical_line_numbers_after_blank_lines(self):
        text, manifest = example()
        text = text.replace(HEADER + '\n', HEADER + '\n\n', 1)
        resign(text, manifest)
        lineage = adapt(text, manifest)['historical_adapter']['record_provenance']
        self.assertEqual([record['csv_row'] for record in lineage], [3, 4])
