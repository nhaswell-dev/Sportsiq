"""Offline security and contract tests for the Hermes invocation boundary."""

import importlib
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import subprocess
import unittest
from unittest.mock import patch

URL = ('https://kalshi.com/markets/kxmvecrosscategory/combo/KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y'
       '?utm_source=kalshiapp_eventdetails&marketTicker=KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y-RXGIQQ2OG')


def integration():
    try:
        return importlib.import_module('sportsiq.hermes_integration')
    except ModuleNotFoundError as error:
        raise AssertionError('Hermes invocation boundary is not implemented') from error


class HermesInputTests(unittest.TestCase):
    def test_valid_exact_url_is_preserved_with_offline_default(self):
        request = integration().validate_request({'url': URL})
        self.assertEqual(request, (URL, 'offline'))

    def test_invalid_urls_and_control_fields_never_start_a_process(self):
        bad_urls = [
            URL.replace('https:', 'http:'), URL.replace('kalshi.com', 'evil.example'),
            URL.replace('kalshi.com', 'kalshi.com.evil.example'),
            URL.replace('kalshi.com', 'www.kalshi.com'),
            URL.replace('kalshi.com', 'user@kalshi.com'),
            URL.replace('kalshi.com', 'kalshi.com:443'),
            URL + '#fragment', URL + '&marketTicker=KX-OTHER', URL + ';touch /tmp/pwn',
            URL + '$(id)', URL + '\n', URL.replace('RXGIQQ2OG', 'rxgiqq2og'),
            URL.replace('RXGIQQ2OG', '%52XGIQQ2OG'),
            URL.replace('marketTicker=', 'marketTicker=OTHER-'),
            URL.replace('marketTicker=', 'ticker='),
            URL.replace('/combo/', '/../'), None, 123, '',
        ]
        requests = [{'url': url} for url in bad_urls]
        requests += [{'url': URL, 'mode': mode} for mode in ('live', True, None, [], {})]
        requests += [{'url': URL, 'executable': '/bin/sh'}, {'url': URL, 'offline': '/etc/passwd'},
                     {'url': URL, 'snapshot': '/etc/passwd'}, {}, [], None]
        with patch('subprocess.run', side_effect=AssertionError('process started')):
            for request in requests:
                with self.subTest(request=request), self.assertRaises(ValueError):
                    integration().invoke(request)


class HermesInvocationTests(unittest.TestCase):
    def test_real_offline_cli_preserves_all_legs_without_local_snapshot(self):
        module = integration()
        with patch.object(module, 'SNAPSHOT', module.ROOT / 'tests/fixtures/absent-snapshot'):
            report = module.invoke({'url': URL})
        self.assertEqual(report['leg_count'], 12)
        self.assertEqual(report['league_counts']['ncaaf'], 10)
        self.assertEqual(report['provenance']['market']['mode'], 'offline')
        self.assertEqual(report['provenance']['market']['requests_made_this_run'], 0)
        self.assertEqual(report['combo_assessment'], 'INSUFFICIENT_DATA')
        self.assertTrue(all(row['analysis']['status'] == 'INSUFFICIENT_DATA' for row in report['legs']))

    def test_live_is_explicit_and_uses_fixed_array_and_sanitized_environment(self):
        module = integration()
        with patch.object(module, 'SNAPSHOT', module.ROOT / 'tests/fixtures/absent-snapshot'):
            report = module.invoke({'url': URL})
        report['provenance']['market']['mode'] = 'live'
        report['provenance']['market']['requests_made_this_run'] = 2
        result = subprocess.CompletedProcess([], 0, json.dumps(report), '')
        with patch('subprocess.run', return_value=result) as run:
            module.invoke({'url': URL, 'mode': 'live-read-only'})
        argv = run.call_args.args[0]
        self.assertEqual(argv[:7], [str(module.PYTHON), '-E', '-s', '-B', '-m', 'sportsiq', 'parlay-report'])
        self.assertEqual(argv[7:11], ['--url', URL, '--format', 'json'])
        self.assertIn('--live', argv)
        self.assertNotIn('--offline', argv)
        self.assertEqual(run.call_args.kwargs, dict(cwd=module.ROOT, env={'LANG': 'C.UTF-8'},
                         stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8',
                         timeout=35, check=False, shell=False))

    def test_process_and_missing_fixture_failures_are_sanitized(self):
        module = integration()
        for failure in (OSError('SECRET'), subprocess.TimeoutExpired('SECRET', 35)):
            with self.subTest(failure=type(failure)), patch('subprocess.run', side_effect=failure):
                with self.assertRaisesRegex(ValueError, '^SportsIQ invocation failed$'):
                    module.invoke({'url': URL})
        with patch.object(module, 'OFFLINE', module.ROOT / 'tests/fixtures/absent.json'):
            with self.assertRaisesRegex(ValueError, '^SportsIQ invocation failed$'):
                module.invoke({'url': URL})

    def test_invalid_child_output_cannot_become_a_success(self):
        module = integration()
        for output in ('not JSON SECRET', '[]', '{}', '{"leg_count":NaN}'):
            with self.subTest(output=output), patch('subprocess.run', return_value=
                    subprocess.CompletedProcess([], 0, output, 'SECRET')):
                with self.assertRaises(ValueError):
                    module.invoke({'url': URL})


class HermesFormattingTests(unittest.TestCase):
    def setUp(self):
        self.module = integration()
        with patch.object(self.module, 'SNAPSHOT', self.module.ROOT / 'tests/fixtures/absent-snapshot'):
            self.report = self.module.invoke({'url': URL})

    def test_changed_identity_counts_or_assessment_are_rejected(self):
        changes = [('market_ticker', 'KX-WRONG'), ('leg_count', 11),
                   ('league_counts', {}), ('combo_assessment', 'RECOMMENDED'),
                   ('original_combo_replay_supported', True)]
        for key, value in changes:
            report = deepcopy(self.report)
            report[key] = value
            with self.subTest(key=key), patch('subprocess.run', return_value=
                    subprocess.CompletedProcess([], 0, json.dumps(report), 'SECRET')):
                with self.assertRaises(ValueError):
                    self.module.invoke({'url': URL})
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 2, 'SECRET', 'SECRET')):
            with self.assertRaisesRegex(ValueError, '^SportsIQ invocation failed$'):
                self.module.invoke({'url': URL})

    def test_unavailable_offline_market_never_falls_back_to_live(self):
        other = URL.replace('RXGIQQ2OG', 'OTHER')
        with patch('subprocess.run', wraps=subprocess.run) as run:
            with self.assertRaises(ValueError):
                self.module.invoke({'url': other})
        self.assertIn('--offline', run.call_args.args[0])
        self.assertNotIn('--live', run.call_args.args[0])

    def test_all_unsupported_leagues_survive_the_wrapper_without_promotion(self):
        import test_consolidated_parlay as consolidated
        from sportsiq.providers.kalshi import extract_parlay, parse_kalshi_url
        from sportsiq.reports.consolidated import consolidate
        bundle, page = consolidated.inputs()
        for index, series in enumerate(('KXNBAGAME', 'KXNCAABGAME', 'KXUNKNOWNGAME')):
            event = series + '-SYNTHETIC'
            bundle['combo_market']['mve_selected_legs'][index].update(
                event_ticker=event, market_ticker=event + '-TEAM')
            bundle['underlying_markets'][index].update(event_ticker=event, ticker=event + '-TEAM')
        report = consolidate(extract_parlay(parse_kalshi_url(URL), bundle), page)
        report['provenance'] = self.report['provenance']
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(report), '')):
            result = self.module.response(self.module.invoke({'url': URL}))
        self.assertEqual([row['league'] for row in result['report']['legs'][:3]], ['nba', 'ncaab', 'unknown'])
        self.assertTrue(all(row['mapping']['outcome'] == 'UNSUPPORTED'
                            and row['analysis']['status'] == 'INSUFFICIENT_DATA'
                            for row in result['report']['legs'][:3]))

    def test_response_preserves_json_and_renders_all_unsupported_legs_and_gaps(self):
        result = self.module.response(self.report)
        self.assertTrue(result['ok'])
        self.assertEqual(result['report'], self.report)
        self.assertEqual(result['text'], '\n\n'.join(result['messages']))
        self.assertIn('Legs: 12', result['text'])
        self.assertIn('ncaaf=10', result['text'])
        self.assertIn('UNSUPPORTED', result['text'])
        self.assertIn('INSUFFICIENT_DATA', result['text'])
        self.assertIn('statistical_adapter_unavailable', result['text'])
        self.assertIn(self.report['provenance']['market']['captured_at'], result['text'])
        self.assertIn(self.report['provenance']['schedule']['captured_at'], result['text'])
        for row in self.report['legs']:
            self.assertIn(row['market_ticker'], result['text'])
        self.assertTrue(all(len(message) <= 3500 for message in result['messages']))

    def test_verified_evidence_never_becomes_a_recommended_selection(self):
        import test_consolidated_parlay as consolidated
        import test_nfl_observed_snapshot as observed
        from sportsiq.providers import nfl_snapshot
        from sportsiq.providers.kalshi import extract_parlay, parse_kalshi_url
        from sportsiq.reports.consolidated import consolidate
        case = observed.ObservedSnapshotTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        bundle, page = consolidated.inputs()
        with patch.dict(nfl_snapshot.APPROVED_SNAPSHOTS, case.approvals, clear=True):
            report = consolidate(extract_parlay(parse_kalshi_url(URL), bundle), page, snapshot=case.path)
        report['provenance'] = self.report['provenance']
        text = self.module.response(report)['text']
        self.assertIn('SUPPORTED_EVIDENCE', text)
        self.assertIn('engine=INSUFFICIENT_DATA', text)
        self.assertIn('verified prior records=10', text)
        self.assertIn('Not a betting recommendation', text)
        self.assertIn('Original combo replay: not verified', text)

    def test_control_characters_and_long_values_are_safe_plain_text_chunks(self):
        report = deepcopy(self.report)
        report['legs'][0]['selection'] = '\x1b\n<b>unsafe</b>😀' * 400
        result = self.module.response(report)
        self.assertNotIn('\x1b', result['text'])
        self.assertNotIn('😀', result['text'])
        self.assertIn('\\u001b', result['text'])
        self.assertTrue(all(len(message) <= 3500 and message.isascii() for message in result['messages']))
        self.assertTrue(all('Not a betting recommendation' in message for message in result['messages']))

    def test_json_stdin_cli_success_and_sanitized_errors(self):
        out = StringIO()
        with patch('sys.stdin', StringIO(json.dumps({'url': URL}))), \
                patch.object(self.module, 'invoke', return_value=self.report), redirect_stdout(out):
            self.assertEqual(self.module.main(), 0)
        self.assertEqual(json.loads(out.getvalue())['report'], self.report)
        for raw in ('SECRET', '[]', '{"url":NaN}', '{"url":"SECRET","url":"OTHER"}',
                    ' ' * 8193, '{"url":"SECRET"}'):
            out = StringIO()
            with patch('sys.stdin', StringIO(raw)), redirect_stdout(out):
                self.assertEqual(self.module.main(), 2)
            result = json.loads(out.getvalue())
            self.assertFalse(result['ok'])
            self.assertNotIn('report', result)
            self.assertNotIn('SECRET', out.getvalue())
            self.assertNotIn('Traceback', out.getvalue())


if __name__ == '__main__':
    unittest.main()
