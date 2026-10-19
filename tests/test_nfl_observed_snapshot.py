"""Synthetic bundles test trusted verification; never actual NFL statistics."""

import csv
from datetime import date, timedelta
import gzip
import hashlib
import importlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
CAPTURE = '2026-10-19T05:34:44.001488+00:00'
CUTOFF = '2026-10-19T23:00:00Z'
FIELDS = ['game_id', 'season', 'season_type', 'week', 'game_date', 'home_team', 'away_team',
          'home_score', 'away_score', 'total_home_score', 'total_away_score', 'location',
          'desc', 'play_type', 'time_of_day', 'play_id']


def digest(body):
    return hashlib.sha256(body).hexdigest()


def service():
    try:
        return importlib.import_module('sportsiq.providers.nfl_snapshot')
    except ModuleNotFoundError as error:
        raise AssertionError('verified observed snapshot path is not implemented') from error


class ObservedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.rows = []
        self.inventory = {'SF': [], 'WAS': []}
        for week in range(1, 6):
            day = (date(2026, 9, 6) + timedelta(weeks=week - 1)).isoformat()
            for team, opponent, own, other in [('SF', 'LA', 21, 7), ('WAS', 'PHI', 14, 28)]:
                gid = f'synthetic-{week}-{team}'
                self.inventory[team].append(gid)
                common = dict(game_id=gid, season='2026', season_type='REG', week=str(week),
                              game_date=day, home_team=team, away_team=opponent,
                              home_score=str(own), away_score=str(other), total_home_score=str(own),
                              total_away_score=str(other), location='Home')
                self.rows.extend([
                    dict(common, desc='Synthetic kickoff', play_type='kickoff',
                         time_of_day=day + 'T17:00:00Z', play_id='1'),
                    dict(common, desc='END GAME', play_type='', time_of_day='', play_id='2'),
                ])
        self.capture_at = CAPTURE
        self.approvals = {}
        self.seal()

    def seal(self):
        buffer = io.StringIO(newline='')
        writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(self.rows)
        raw = gzip.compress(buffer.getvalue().encode(), mtime=0)
        raw_hash = digest(raw)
        asset = dict(id=123, name='play_by_play_2026.csv.gz', size=len(raw),
                     created_at='2026-10-19T04:32:52Z', updated_at='2026-10-19T04:32:52Z',
                     digest='sha256:' + raw_hash)
        capture = {'asset': {'retrieved_at': self.capture_at,
                            'request_started_at': '2026-10-19T05:34:43+00:00',
                            'response_status': 200, 'sha256': raw_hash, 'bytes': len(raw),
                            'publisher_asset_id': 123, 'publisher_updated_at': asset['updated_at'],
                            'publisher_digest': asset['digest']}}
        bodies = {
            'play_by_play_2026.csv.gz': raw,
            'capture.json': json.dumps(capture).encode(),
            'pbp_release.json': json.dumps({'assets': [asset], 'body': 'Synthetic PBP release'}).encode(),
            'data_license.md': b'Attribution 4.0 International\nSynthetic test evidence only.\n',
            'org_readme.md': b'Synthetic test scope: non-FTN PBP CC-BY 4.0.\n',
            'schedule_reference.json': json.dumps({'checked_at': '2026-10-19T05:36:11Z',
                'results': [{'url': 'https://www.49ers.com/schedule/',
                             'description': 'Synthetic test schedule October 19 2026 5:15 PM PDT'}]}).encode(),
        }
        for name, body in bodies.items():
            (self.path / name).write_bytes(body)
        manifest = {'files': [{'file': name, 'bytes': len(body), 'sha256': digest(body)}
                              for name, body in bodies.items()], 'raw_dataset_sha256': raw_hash}
        body = json.dumps(manifest).encode()
        (self.path / 'snapshot_manifest.json').write_bytes(body)
        self.approvals = {raw_hash: {'manifest_sha256': digest(body), 'capture_at': self.capture_at,
            'asset_id': 123, 'expected_history': self.inventory,
            'schedule_observed_at': '2026-10-19T05:36:11Z',
            'scheduled_kickoff': '2026-10-20T00:15:00Z',
            'license_review': 'Synthetic bundle authorized ONLY inside these tests'}}

    def assess(self, *, cutoff=CUTOFF, selection='49ers'):
        module = service()
        with patch.dict(module.APPROVED_SNAPSHOTS, self.approvals, clear=True):
            return module.assess_snapshot(self.path, cutoff=cutoff, selection=selection)

    def test_verified_final_markers_produce_observed_metrics_without_exact_end_times(self):
        result = self.assess()
        leg = result['legs'][0]
        self.assertEqual(result['snapshot_status'], 'ACCEPTED_OBSERVED_HISTORY')
        self.assertEqual(leg['assessment'], 'INSUFFICIENT_DATA')
        metrics = {m['name']: m for m in leg['metrics']}
        self.assertEqual(metrics['record']['selected']['wins'], 5)
        self.assertEqual(metrics['points']['selected']['scored'], 105)
        self.assertEqual(metrics['home_away']['selected']['home']['games'], 5)
        self.assertEqual(len(result['completion_provenance']), 10)
        self.assertTrue(all(p['completion_basis'] == 'observed_complete_by_snapshot'
                            and p['completed_at'] is None and p['completed_no_later_than'] == CAPTURE
                            for p in result['completion_provenance']))
        self.assertIsNone(leg['actual_kickoff'])
        self.assertIn('actual_kickoff_unverified', leg['uncertainty'])

    def test_cutoff_equality_and_late_snapshots_are_rejected_before_game_parsing(self):
        for cutoff in (CAPTURE, '2026-10-18T19:00:00Z'):
            with patch.object(service(), '_records', side_effect=AssertionError('must not parse late data')):
                result = self.assess(cutoff=cutoff)
            self.assertEqual(result['snapshot_status'], 'BLOCKED')
            self.assertIn('snapshot_not_before_cutoff', result['snapshot_missing_evidence'])
            self.assertEqual(result['legs'][0]['metrics'], [])

    def test_rams_cannot_use_this_later_capture_as_retrospective_pregame_evidence(self):
        result = self.assess(selection='rams', cutoff='2026-10-18T19:00:00Z')
        self.assertEqual(result['snapshot_status'], 'BLOCKED')
        self.assertEqual(result['legs'][0]['metrics'], [])
        self.assertEqual(result['completion_provenance'], [])
        self.assertEqual(result['snapshot_captured_at'], CAPTURE)

    def test_changed_bytes_cannot_be_approved_by_a_caller_manifest_flag(self):
        path = self.path / 'snapshot_manifest.json'
        manifest = json.loads(path.read_text())
        manifest['approved'] = True
        path.write_text(json.dumps(manifest))
        result = self.assess()
        self.assertEqual(result['snapshot_status'], 'BLOCKED')
        self.assertIn('snapshot_not_code_approved', result['snapshot_missing_evidence'])

    def test_changed_source_or_capture_bytes_fail_integrity_without_resealing(self):
        for name in ('play_by_play_2026.csv.gz', 'capture.json', 'data_license.md', 'schedule_reference.json'):
            with self.subTest(file=name):
                self.seal()
                path = self.path / name
                path.write_bytes(path.read_bytes() + b'changed')
                result = self.assess()
                self.assertEqual(result['snapshot_status'], 'BLOCKED')
                self.assertIn('snapshot_integrity_failure', result['snapshot_missing_evidence'])

    def test_missing_license_evidence_fails_closed(self):
        (self.path / 'data_license.md').unlink()
        result = self.assess()
        self.assertEqual(result['snapshot_status'], 'BLOCKED')
        self.assertEqual(result['legs'][0]['metrics'], [])

    def test_incomplete_or_duplicate_terminal_records_are_rejected(self):
        original = list(self.rows)
        for rows in (original[:-1], original + [dict(original[-1], play_id='3')]):
            self.rows = rows
            self.seal()
            result = self.assess()
            self.assertEqual(result['snapshot_status'], 'BLOCKED')
            self.assertIn('final_status_missing_or_conflicting', result['snapshot_missing_evidence'])

    def test_future_timed_event_cannot_be_hidden_in_an_old_dated_game(self):
        self.rows[0]['time_of_day'] = '2026-10-20T17:00:00Z'
        self.seal()
        result = self.assess()
        self.assertEqual(result['snapshot_status'], 'BLOCKED')
        self.assertIn('event_timing_unverified', result['snapshot_missing_evidence'])

    def test_target_result_is_excluded_before_score_or_status_interpretation(self):
        self.rows.append(dict(self.rows[0], game_id='2026_06_WAS_SF', home_team='SF', away_team='WAS',
                              game_date='2026-10-19', home_score='TARGET-DO-NOT-ECHO', desc='TARGET-DO-NOT-ECHO'))
        self.seal()
        result = self.assess()
        self.assertEqual(result['snapshot_status'], 'ACCEPTED_OBSERVED_HISTORY')
        self.assertEqual(len(result['completion_provenance']), 10)
        self.assertIn('2026_06_WAS_SF', result['target_and_later_games_excluded'])
        self.assertNotIn('TARGET-DO-NOT-ECHO', json.dumps(result))

    def test_conflicting_team_or_final_score_metadata_is_rejected(self):
        self.rows[1]['home_score'] = '99'
        self.seal()
        result = self.assess()
        self.assertEqual(result['snapshot_status'], 'BLOCKED')
        self.assertIn('conflicting_game_metadata', result['snapshot_missing_evidence'])

    def test_reviewed_inventory_must_match_all_expected_games(self):
        self.rows = self.rows[2:]
        self.seal()
        result = self.assess()
        self.assertEqual(result['snapshot_status'], 'BLOCKED')
        self.assertIn('reviewed_snapshot_inventory_incomplete', result['snapshot_missing_evidence'])

    def test_prior_game_date_must_agree_with_actual_start_and_season(self):
        self.rows[0]['time_of_day'] = '2025-09-06T17:00:00Z'
        self.seal()
        result = self.assess()
        self.assertEqual(result['snapshot_status'], 'BLOCKED')

    def test_neutral_games_remain_separate_and_unknown_target_venue_is_not_invented(self):
        self.rows[0]['location'] = self.rows[1]['location'] = 'Neutral'
        self.seal()
        leg = self.assess()['legs'][0]
        split = next(m for m in leg['metrics'] if m['name'] == 'home_away')['selected']
        self.assertEqual(split['neutral']['games'], 1)
        self.assertEqual(split['home']['games'], 4)
        self.assertEqual(leg['selected_venue'], 'unknown')

    def capture_engine_input(self):
        module = service()
        original = module.assess_nfl
        captured = {}

        def intercept(payload, **kwargs):
            import copy
            captured.update(payload=copy.deepcopy(payload), evidence=kwargs.get('observed_evidence'))
            return original(payload, **kwargs)

        with patch.object(module, 'assess_nfl', side_effect=intercept):
            result = self.assess()
        self.assertEqual(result['snapshot_status'], 'ACCEPTED_OBSERVED_HISTORY')
        return captured

    def test_bounded_json_records_and_approval_flags_cannot_bypass_the_verifier(self):
        from sportsiq.analysis.nfl import assess_nfl
        captured = self.capture_engine_input()
        for flag in (None, True, {'approved': True}):
            result = assess_nfl(captured['payload'], observed_evidence=flag)
            self.assertEqual(result['legs'][0]['metrics'], [])
            self.assertTrue(result['excluded'])

    def test_issued_evidence_is_bound_to_source_and_record_content(self):
        from sportsiq.analysis.nfl import assess_nfl
        captured = self.capture_engine_input()
        payload = captured['payload']
        payload['sources'][0]['records'][0]['home_points'] = 199
        payload['sources'][0]['content_sha256'] = digest(json.dumps(
            payload['sources'][0]['records'], sort_keys=True, separators=(',', ':')).encode())
        result = assess_nfl(payload, observed_evidence=captured['evidence'])
        record = next(m for m in result['legs'][0]['metrics'] if m['name'] == 'record')
        self.assertIsNone(record['selected'])
        self.assertIsNone(record['opponent'])

    def test_ordinary_exact_fixture_rules_are_not_relaxed(self):
        from sportsiq.analysis.nfl import assess_nfl
        from test_nfl_assessment import full_fixture, seal
        fixture = full_fixture()
        row = fixture['sources'][0]['records'][1]
        row['completed_no_later_than'] = row.pop('completed_at')
        seal(fixture['sources'][0])
        result = assess_nfl(fixture, observed_evidence={'approved': True})
        self.assertNotIn(row['game_id'], result['legs'][0]['metrics'][0]['game_ids'])

    def test_prospective_cutoff_must_precede_the_verified_cached_schedule(self):
        result = self.assess(cutoff='2026-10-20T00:15:00Z')
        self.assertEqual(result['snapshot_status'], 'BLOCKED')
        self.assertIn('cutoff_or_schedule_not_pregame', result['snapshot_missing_evidence'])

    def test_observed_points_include_descriptive_point_differential(self):
        metrics = self.assess()['legs'][0]['metrics']
        points = next(m for m in metrics if m['name'] == 'points')['selected']
        self.assertEqual(points['point_differential'], points['scored'] - points['allowed'])
        self.assertEqual(points['point_differential_per_game'],
                         (points['scored'] - points['allowed']) / points['games'])

    def test_missing_capture_timestamp_is_not_replaced_by_mtime_or_now(self):
        path = self.path / 'capture.json'
        capture = json.loads(path.read_text())
        capture['asset'].pop('retrieved_at')
        body = json.dumps(capture).encode()
        path.write_bytes(body)
        manifest_path = self.path / 'snapshot_manifest.json'
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest['files']:
            if entry['file'] == path.name:
                entry.update(bytes=len(body), sha256=digest(body))
        body = json.dumps(manifest).encode()
        manifest_path.write_bytes(body)
        next(iter(self.approvals.values()))['manifest_sha256'] = digest(body)
        result = self.assess()
        self.assertEqual(result['snapshot_status'], 'BLOCKED')
        self.assertEqual(result['legs'][0]['metrics'], [])

    def test_later_non_target_result_cannot_contaminate_prior_history(self):
        self.rows.append(dict(self.rows[0], game_id='future-game', game_date='2026-10-20',
                              home_score='FUTURE-DO-NOT-ECHO', desc='END GAME'))
        self.seal()
        result = self.assess()
        self.assertEqual(result['snapshot_status'], 'ACCEPTED_OBSERVED_HISTORY')
        self.assertIn('future-game', result['target_and_later_games_excluded'])
        self.assertEqual(len(result['completion_provenance']), 10)
        self.assertNotIn('FUTURE-DO-NOT-ECHO', json.dumps(result))

    def test_exact_and_bounded_copies_of_the_same_game_are_both_quarantined(self):
        import copy
        from sportsiq.analysis.nfl import assess_nfl
        captured = self.capture_engine_input()
        payload = captured['payload']
        source = copy.deepcopy(payload['sources'][0])
        record = dict(source['records'][0])
        record.update(kind='game_result', completed_at='2026-09-06T20:00:00Z')
        record.pop('completed_no_later_than')
        record.pop('completion_evidence')
        source.update(source_id='exact-fixture', records=[record])
        source['content_sha256'] = digest(json.dumps(source['records'], sort_keys=True, separators=(',', ':')).encode())
        payload['sources'].append(source)
        result = assess_nfl(payload, observed_evidence=captured['evidence'])
        self.assertIn('ambiguous_record_identity', {r['reason'] for r in result['excluded']})
        self.assertNotIn(record['game_id'], result['legs'][0]['metrics'][0]['game_ids'])

    def test_cli_accepts_only_local_snapshot_and_explicit_cutoff(self):
        from contextlib import redirect_stdout
        from io import StringIO
        try:
            module = importlib.import_module('sportsiq.analysis.snapshot')
        except ModuleNotFoundError as error:
            self.fail(str(error))
        for fmt in ('json', 'summary'):
            out = StringIO()
            with patch.dict(service().APPROVED_SNAPSHOTS, self.approvals, clear=True), redirect_stdout(out):
                code = module.main(['--snapshot', str(self.path), '--cutoff', CUTOFF, '--format', fmt])
            self.assertEqual(code, 0)
            self.assertIn('ACCEPTED_OBSERVED_HISTORY', out.getvalue())
            self.assertIn('completed_no_later_than', out.getvalue())
            self.assertIn('INSUFFICIENT_DATA', out.getvalue())
            self.assertTrue(all(line == line.rstrip() for line in out.getvalue().splitlines()))

    def test_snapshot_path_does_not_access_network_database_or_credentials(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')) as request, \
                patch('socket.create_connection', side_effect=AssertionError('network')) as connect, \
                patch('sqlite3.connect', side_effect=AssertionError('database')) as database:
            original = Path.open

            def guarded(path, *args, **kwargs):
                if path.name.startswith('.env'):
                    raise AssertionError('credential access')
                return original(path, *args, **kwargs)

            with patch.object(Path, 'open', guarded):
                result = self.assess()
            self.assertEqual(result['snapshot_status'], 'ACCEPTED_OBSERVED_HISTORY')
            request.assert_not_called()
            connect.assert_not_called()
            database.assert_not_called()

    def test_conflicting_play_identity_cannot_be_resolved_by_choosing_earlier_time(self):
        self.rows.insert(1, dict(self.rows[0], time_of_day='2026-09-06T18:00:00Z', desc='Conflicting duplicate'))
        self.seal()
        self.assertEqual(self.assess()['snapshot_status'], 'BLOCKED')

    def test_provider_does_not_claim_acceptance_if_shared_engine_rejects_evidence(self):
        module = service()
        original = module.assess_nfl

        def rejecting_engine(payload, **kwargs):
            # Exercise a failed downstream verification, not a synthetic success stub.
            return original(payload)

        with patch.object(module, 'assess_nfl', side_effect=rejecting_engine):
            result = self.assess()
        self.assertEqual(result['snapshot_status'], 'BLOCKED')
        self.assertEqual(result['legs'][0]['metrics'], [])
