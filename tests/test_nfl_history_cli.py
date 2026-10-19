"""Offline historical adapter CLI, including explicit real-data refusal artifacts."""

from contextlib import redirect_stderr, redirect_stdout
import importlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from test_nfl_history import HEADER, adapt, example

ROOT = Path(__file__).resolve().parent.parent


def main(argv):
    try:
        module = importlib.import_module('sportsiq.analysis.history')
    except ModuleNotFoundError as error:
        raise AssertionError('historical CSV CLI is not implemented') from error
    return module.main(argv)


class NFLHistoryCLITests(unittest.TestCase):
    def run_input(self, text, manifest, fmt='json'):
        out, err = StringIO(), StringIO()
        with TemporaryDirectory(dir=ROOT) as directory:
            csv_path, manifest_path = Path(directory) / 'games.csv', Path(directory) / 'manifest.json'
            csv_path.write_bytes(text.encode() if isinstance(text, str) else text)
            manifest_path.write_text(json.dumps(manifest) if isinstance(manifest, dict) else manifest)
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    code = main(['--csv', str(csv_path), '--manifest', str(manifest_path), '--format', fmt])
                except SystemExit as error:
                    code = error.code
        return code, out.getvalue(), err.getvalue()

    def test_json_and_readable_modes_exercise_the_real_adapter(self):
        text, manifest = example()
        code, out, err = self.run_input(text, manifest)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), adapt(text, manifest))
        code, out, err = self.run_input(text, manifest, 'summary')
        self.assertEqual(code, 0, err)
        for value in ('NOT ACTUAL NFL STATISTICS', 'SYNTHETIC_ONLY', 'csv_row', 'raw_snapshot_sha256',
                      'DECLARED_SET_MATCHED', 'INSUFFICIENT_DATA'):
            self.assertIn(value, out)

    def test_no_network_database_or_credential_access(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')) as request, \
                patch('socket.create_connection', side_effect=AssertionError('network')) as connection, \
                patch('sqlite3.connect', side_effect=AssertionError('database')) as database:
            original = Path.open

            def guarded(path, *args, **kwargs):
                if path.name.startswith('.env'):
                    raise AssertionError('credential read')
                return original(path, *args, **kwargs)

            with patch.object(Path, 'open', guarded):
                code, out, err = self.run_input(*example())
            self.assertEqual(code, 0, err)
            request.assert_not_called()
            connection.assert_not_called()
            database.assert_not_called()

    def test_malformed_input_is_sanitized_and_bounded(self):
        text, manifest = example()
        cases = [(text, '{"schema_version":1,"schema_version":2}'), (text, '[]'),
                 (text, '{"value":NaN}'), (text, '{"value":1e999}'),
                 (b'\xff', manifest), (b' ' * (2 * 1024 * 1024 + 1), manifest),
                 ('DO_NOT_ECHO', manifest)]
        for body, meta in cases:
            code, out, err = self.run_input(body, meta)
            self.assertEqual(code, 2)
            self.assertEqual(out, '')
            self.assertIn('invalid offline NFL history input', err)
            self.assertNotIn('Traceback', err)
            self.assertNotIn('DO_NOT_ECHO', err)

    def test_committed_synthetic_and_blocked_inputs_do_not_claim_real_statistics(self):
        fixtures = ROOT / 'tests/fixtures'
        synthetic_csv, synthetic_manifest = fixtures / 'nfl_history_synthetic.csv', fixtures / 'nfl_history_synthetic.json'
        blocked_manifest = fixtures / 'nfl_history_blocked.json'
        for path in (synthetic_csv, synthetic_manifest, blocked_manifest, fixtures / 'nfl_history_empty.csv'):
            self.assertTrue(path.exists(), 'historical example fixture missing')
        sample = adapt(synthetic_csv.read_text(), json.loads(synthetic_manifest.read_text()))
        blocked = adapt((fixtures / 'nfl_history_empty.csv').read_text(), json.loads(blocked_manifest.read_text()))
        self.assertEqual(sample['data_kind'], 'synthetic')
        self.assertTrue(all(leg['metrics'] for leg in sample['legs']))
        self.assertEqual(blocked['data_kind'], 'observed')
        self.assertEqual(blocked['historical_adapter']['status'], 'BLOCKED')
        self.assertEqual(len(blocked['legs']), 2)
        self.assertTrue(all(not leg['metrics'] for leg in blocked['legs']))
        self.assertIn('real_dataset_not_approved', blocked['legs'][0]['missing_data'])

    def test_committed_real_target_refusal_report_is_reproducible(self):
        path = ROOT / 'docs/nfl-real-historical-report.json'
        self.assertTrue(path.exists(), 'generated refusal report missing')
        fixtures = ROOT / 'tests/fixtures'
        expected = adapt((fixtures / 'nfl_history_empty.csv').read_text(),
                         json.loads((fixtures / 'nfl_history_blocked.json').read_text()))
        self.assertEqual(json.loads(path.read_text()), expected)
        self.assertTrue(all(not leg['metrics'] for leg in expected['legs']))
