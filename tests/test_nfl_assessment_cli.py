"""Exercise the offline-only CLI and terminal-safe descriptive report."""

from contextlib import redirect_stdout, redirect_stderr
import importlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from test_nfl_assessment import assess, full_fixture

ROOT = Path(__file__).resolve().parent.parent


def main(argv):
    try:
        module = importlib.import_module('sportsiq.analysis.__main__')
    except ModuleNotFoundError as error:
        raise AssertionError('offline NFL assessment CLI is not implemented') from error
    return module.main(argv)


class AssessmentCLITests(unittest.TestCase):
    def test_committed_synthetic_example_has_two_independent_leg_reports(self):
        path = ROOT / 'tests/fixtures/nfl_assessment_synthetic.json'
        self.assertTrue(path.exists(), 'two-leg synthetic assessment fixture is missing')
        code, out, err = self.run_input(path.read_text())
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(len(result['legs']), 2)
        self.assertEqual(result['data_kind'], 'synthetic')
        self.assertTrue(all(leg['metrics'] for leg in result['legs']))
        self.assertTrue(all(leg['assessment'] == 'INSUFFICIENT_DATA' for leg in result['legs']))
        self.assertEqual(len({leg['analysis_cutoff'] for leg in result['legs']}), 1)

    def run_input(self, body, fmt='json'):
        out, err = StringIO(), StringIO()
        with TemporaryDirectory(dir=ROOT) as directory:
            fixture = Path(directory) / 'fixture.json'
            fixture.write_bytes(body if isinstance(body, bytes) else body.encode())
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    code = main(['--fixture', str(fixture), '--format', fmt])
                except SystemExit as error:
                    code = error.code
        return code, out.getvalue(), err.getvalue()

    def test_json_cli_exercises_real_service_without_probabilities_or_ratings(self):
        code, out, err = self.run_input(json.dumps(full_fixture()))
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result, assess(full_fixture()))
        self.assertIn('SYNTHETIC DATA', result['notice'])
        self.assertNotIn('winning_probability', out)
        self.assertNotIn('expected_value', out)
        self.assertNotIn('recommendation', out)

    def test_readable_report_lists_metrics_evidence_sources_and_gaps(self):
        code, out, err = self.run_input(json.dumps(full_fixture()), 'summary')
        self.assertEqual(code, 0, err)
        for text in ('NOT ACTUAL NFL STATISTICS', 'INSUFFICIENT_DATA', '2026-10-18T19:00:00+00:00',
                     'record', 'home_away', 'points', 'opponent_strength', 'history',
                     'Evidence for', 'Evidence against', 'Missing', 'Uncertainty',
                     'published_at', 'revision_at', 'available_at', 'retrieved_at', 'content_sha256'):
            self.assertIn(text, out)

    def test_invalid_json_is_sanitized_without_traceback_or_input_echo(self):
        for body in ('{"schema_version":1,"schema_version":2}', '{"value":NaN}',
                     '{"value":Infinity}', '{"value":1e999}', '[]', '"DO-NOT-ECHO"',
                     '{"sources":"DO-NOT-ECHO"}', b'\xff', b' ' * (2 * 1024 * 1024 + 1)):
            with self.subTest(body_type=type(body).__name__):
                code, out, err = self.run_input(body)
                self.assertEqual(code, 2)
                self.assertEqual(out, '')
                self.assertIn('invalid offline NFL analysis fixture', err)
                self.assertNotIn('Traceback', err)
                self.assertNotIn('DO-NOT-ECHO', err)

    def test_cli_cannot_contact_network_open_database_or_read_credentials(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')) as request, \
                patch('socket.create_connection', side_effect=AssertionError('network')) as connect, \
                patch('sqlite3.connect', side_effect=AssertionError('database')) as database:
            original = Path.open

            def guarded(path, *args, **kwargs):
                if path.name.startswith('.env'):
                    raise AssertionError('credentials')
                return original(path, *args, **kwargs)

            with patch.object(Path, 'open', guarded):
                code, out, err = self.run_input(json.dumps(full_fixture()))
            self.assertEqual(code, 0, err)
            self.assertTrue(out)
            request.assert_not_called()
            connect.assert_not_called()
            database.assert_not_called()

    def test_report_escapes_terminal_control_characters(self):
        try:
            module = importlib.import_module('sportsiq.reports.nfl_assessment')
        except ModuleNotFoundError as error:
            self.fail(str(error))
        result = assess(full_fixture())
        result['legs'][0]['market_ticker'] = '\x1b[2J\n'
        result['sources'][0]['reference'] = '\x1b[31m\n'
        result['legs'][0]['evidence_for'].append('\x1b[2J\n')
        out = module.assessment_summary(result)
        self.assertNotIn('\x1b', out)
        self.assertIn('\\u001b', out)
