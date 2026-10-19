"""Consolidation uses saved projections; no live sources or credentials."""

from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr

import importlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from sportsiq.providers.kalshi import extract_parlay, parse_kalshi_url

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/nfl_combo_observed.json'
URL = ('https://kalshi.com/markets/kxmvecrosscategory/combo/KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y'
       '?utm_source=kalshiapp_eventdetails&marketTicker=KXMVECROSSCATEGORY-S2026KRL562BKN32IAT7Y-RXGIQQ2OG')
NOW = '2026-10-19T12:00:00Z'


def inputs():
    saved = json.loads(FIXTURE.read_text())
    raw = saved['extraction']
    bundle = {'combo_market': raw['raw_combo_market'],
              'underlying_markets': [row['raw_market'] for row in raw['legs']],
              'milestones': []}
    return bundle, saved['games_page']


def service():
    try:
        return importlib.import_module('sportsiq.reports.consolidated')
    except ModuleNotFoundError as error:
        raise AssertionError('consolidated reporting is not implemented') from error


class ConsolidatedTests(unittest.TestCase):
    def setUp(self):
        self.bundle, self.page = inputs()

    def report(self, **kwargs):
        extraction = extract_parlay(parse_kalshi_url(URL), self.bundle)
        return service().consolidate(extraction, self.page, generated_at=NOW, **kwargs)

    def test_all_twelve_exact_selections_have_separate_mapping_and_analysis_status(self):
        report = self.report()
        self.assertEqual(report['leg_count'], 12)
        self.assertEqual(report['league_counts'], {'nfl': 2, 'nba': 0, 'ncaaf': 10, 'ncaab': 0, 'unknown': 0})
        self.assertEqual([row['mapping']['outcome'] for row in report['legs']], ['UNSUPPORTED'] * 10 + ['MATCHED'] * 2)
        self.assertTrue(all(row['analysis']['status'] == 'INSUFFICIENT_DATA' for row in report['legs']))
        expected = self.bundle['combo_market']['mve_selected_legs']
        actual = [{k: row[k] for k in ('event_ticker', 'market_ticker', 'side')} for row in report['legs']]
        self.assertEqual(actual, expected)
        self.assertFalse(report['original_combo_replay_supported'])
        self.assertEqual(report['combo_assessment'], 'INSUFFICIENT_DATA')
        self.assertEqual(report['generated_at'], NOW)

    def snapshot(self):
        import test_nfl_observed_snapshot as observed
        case = observed.ObservedSnapshotTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_verified_history_is_descriptive_evidence_not_a_supported_selection(self):
        from sportsiq.providers import nfl_snapshot
        case = self.snapshot()
        with patch.dict(nfl_snapshot.APPROVED_SNAPSHOTS, case.approvals, clear=True):
            report = self.report(snapshot=case.path)
        rams, sf = [row['analysis'] for row in report['legs'][-2:]]
        self.assertEqual(sf['status'], 'SUPPORTED_EVIDENCE')
        self.assertEqual(sf['engine_assessment'], 'INSUFFICIENT_DATA')
        self.assertEqual(sf['cutoff'], '2026-10-19T23:00:00+00:00')
        self.assertEqual(len(sf['completion_provenance']), 10)
        record = next(m for m in sf['metrics'] if m['name'] == 'record')
        self.assertEqual(record['selected']['games'], 5)
        self.assertTrue(sf['source_provenance'])
        self.assertEqual(rams['status'], 'INSUFFICIENT_DATA')
        self.assertEqual(rams['metrics'], [])
        self.assertIn('snapshot_not_before_cutoff', rams['missing_evidence'])
        self.assertFalse(report['original_combo_replay_supported'])

    def test_matched_schedule_disagreeing_with_verified_history_is_not_evidence_ready(self):
        from sportsiq.providers import nfl_snapshot
        case = self.snapshot()
        self.page['data'][1]['date'] = '2026-10-20T01:15:00Z'
        with patch.dict(nfl_snapshot.APPROVED_SNAPSHOTS, case.approvals, clear=True):
            sf = self.report(snapshot=case.path)['legs'][-1]
        self.assertEqual(sf['mapping']['outcome'], 'MATCHED')
        self.assertEqual(sf['analysis']['status'], 'INSUFFICIENT_DATA')
        self.assertEqual(sf['analysis']['metrics'], [])
        self.assertIn('matched_game_assessment_context_conflict', sf['analysis']['missing_evidence'])

    def test_exact_market_id_cannot_attach_history_for_a_different_proposition(self):
        from sportsiq.providers import nfl_snapshot
        case = self.snapshot()
        rams = self.bundle['underlying_markets'][-2]
        sf = self.bundle['underlying_markets'][-1]
        for key in ('rules_primary', 'yes_sub_title', 'no_sub_title', 'title', 'custom_strike'):
            sf[key] = deepcopy(rams[key])
        with patch.dict(nfl_snapshot.APPROVED_SNAPSHOTS, case.approvals, clear=True):
            row = self.report(snapshot=case.path)['legs'][-1]
        self.assertEqual(row['mapping']['outcome'], 'MATCHED')
        self.assertEqual(row['analysis']['status'], 'INSUFFICIENT_DATA')
        self.assertEqual(row['analysis']['metrics'], [])

    def test_cli_defaults_are_offline_and_both_formats_preserve_identical_selections(self):
        try:
            module = importlib.import_module('sportsiq.parlay_report')
        except ModuleNotFoundError as error:
            self.fail(str(error))
        from sportsiq.cli import main
        outputs = {}
        for fmt in ('json', 'summary'):
            out = StringIO()
            with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network')), \
                    patch('sqlite3.connect', side_effect=AssertionError('database')), \
                    patch('sportsiq.cli._project_key', side_effect=AssertionError('credentials')), redirect_stdout(out):
                self.assertEqual(main(['parlay-report', '--url', URL, '--snapshot', str(ROOT / 'missing-snapshot'),
                                       '--format', fmt]), 0)
            outputs[fmt] = out.getvalue()
        result = json.loads(outputs['json'])
        self.assertEqual(result['leg_count'], 12)
        self.assertEqual(result['provenance']['market']['requests_made_this_run'], 0)
        self.assertTrue(result['provenance']['market']['sha256'])
        for row in result['legs']:
            self.assertIn(row['market_ticker'], outputs['summary'])
            self.assertIn(row['analysis']['status'], outputs['summary'])
        self.assertEqual(module.DEFAULT_OFFLINE, FIXTURE)
        original = json.loads(FIXTURE.read_text())
        self.assertEqual(result['provenance']['market']['captured_at'], original['extraction']['observed_at'])
        self.assertEqual(result['provenance']['schedule']['captured_at'],
                         original['games_page']['verification']['retrieved_at'])

    def test_all_required_league_classifications_can_coexist_without_adapters(self):
        for index, series in enumerate(('KXNBAGAME', 'KXNCAABGAME', 'KXUNKNOWNGAME')):
            selected = self.bundle['combo_market']['mve_selected_legs'][index]
            market = self.bundle['underlying_markets'][index]
            event = series + '-SYNTHETIC'
            selected.update(event_ticker=event, market_ticker=event + '-TEAM')
            market.update(event_ticker=event, ticker=event + '-TEAM')
        result = self.report()
        self.assertEqual([row['league'] for row in result['legs'][:3]], ['nba', 'ncaab', 'unknown'])
        self.assertEqual(sum(result['league_counts'].values()), result['leg_count'])
        self.assertTrue(all(row['mapping']['outcome'] == 'UNSUPPORTED' for row in result['legs'][:3]))

    def test_optional_missing_market_text_is_visible_without_losing_legs(self):
        market = self.bundle['underlying_markets'][-1]
        market.pop('rules_primary')
        market.pop('title')
        row = self.report()['legs'][-1]
        self.assertIsNone(row['matchup'])
        self.assertEqual(row['mapping']['outcome'], 'UNSUPPORTED')
        self.assertEqual(row['analysis']['status'], 'INSUFFICIENT_DATA')
        self.assertIn('missing_market_description', row['mapping']['evidence']['gaps'])

    def test_incomplete_underlying_inventory_is_rejected_not_silently_shortened(self):
        self.bundle['underlying_markets'].pop()
        with self.assertRaisesRegex(ValueError, 'incomplete underlying'):
            self.report()

    def test_missing_snapshot_keeps_successful_matches_but_no_statistics(self):
        case = self.snapshot()
        result = self.report(snapshot=case.path / 'absent')
        for row in result['legs'][-2:]:
            self.assertEqual(row['mapping']['outcome'], 'MATCHED')
            self.assertEqual(row['analysis']['status'], 'INSUFFICIENT_DATA')
            self.assertEqual(row['analysis']['metrics'], [])
            self.assertTrue(row['analysis']['missing_evidence'])

    def test_malformed_snapshot_manifest_cannot_crash_or_authorize_evidence(self):
        case = self.snapshot()
        (case.path / 'snapshot_manifest.json').write_text('[]')
        result = self.report(snapshot=case.path)
        self.assertTrue(all(row['analysis']['status'] == 'INSUFFICIENT_DATA' for row in result['legs']))

    def test_tampered_capture_is_rejected_by_existing_validator(self):
        from sportsiq.providers import nfl_snapshot
        case = self.snapshot()
        with (case.path / 'capture.json').open('ab') as stream:
            stream.write(b'APPROVED BY CALLER')
        with patch.dict(nfl_snapshot.APPROVED_SNAPSHOTS, case.approvals, clear=True):
            result = self.report(snapshot=case.path)
        self.assertEqual(result['legs'][-1]['analysis']['metrics'], [])
        self.assertIn('snapshot_integrity_failure', result['legs'][-1]['analysis']['missing_evidence'])

    def test_common_original_combo_cutoff_never_uses_the_later_49ers_capture(self):
        from sportsiq.providers import nfl_snapshot
        case = self.snapshot()
        with patch.dict(nfl_snapshot.APPROVED_SNAPSHOTS, case.approvals, clear=True), \
                patch.object(nfl_snapshot, '_records', side_effect=AssertionError('late data parsing')):
            result = self.report(snapshot=case.path, cutoff='2026-10-16T12:00:00Z')
        self.assertEqual(result['analysis_cutoff'], '2026-10-16T12:00:00+00:00')
        for row in result['legs'][-2:]:
            self.assertEqual(row['analysis']['status'], 'INSUFFICIENT_DATA')
            self.assertIn('snapshot_not_before_cutoff', row['analysis']['missing_evidence'])

    def test_no_side_remains_literal_and_cannot_receive_yes_history(self):
        self.bundle['combo_market']['mve_selected_legs'][-1]['side'] = 'no'
        case = self.snapshot()
        result = self.report(snapshot=case.path)
        row = result['legs'][-1]
        self.assertEqual(row['side'], 'no')
        self.assertEqual(row['mapping']['side'], 'no')
        self.assertEqual(row['mapping']['outcome'], 'MATCHED')
        self.assertEqual(row['analysis']['metrics'], [])
        self.assertIn('historical_adapter_not_available_for_selection', row['analysis']['missing_evidence'])

    def test_ambiguous_and_not_found_are_not_promoted_to_ready_analysis(self):
        sf = self.page['data'][1]
        self.page['data'].append(dict(sf, id=1399999))
        ambiguous = self.report()['legs'][-1]
        self.assertEqual(ambiguous['mapping']['outcome'], 'AMBIGUOUS')
        self.assertEqual(ambiguous['analysis']['status'], 'INSUFFICIENT_DATA')
        self.page['data'] = [dict(sf, date='2026-10-21T00:15:00Z')]
        missing = self.report()['legs'][-1]
        self.assertEqual(missing['mapping']['outcome'], 'NOT_FOUND')
        self.assertEqual(missing['analysis']['metrics'], [])

    def test_duplicate_provider_ids_are_rejected_before_raw_source_join(self):
        self.page['data'].append(deepcopy(self.page['data'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate provider'):
            self.report()

    def test_frozen_inputs_and_clock_produce_identical_json_and_text(self):
        first, second = self.report(), self.report()
        self.assertEqual(first, second)
        self.assertEqual(service().consolidated_summary(first), service().consolidated_summary(second))
        text = service().consolidated_summary(first)
        for row in first['legs']:
            self.assertIn(json.dumps(row['market_ticker']), text)
            self.assertIn(json.dumps(row['mapping']['outcome']), text)
            self.assertIn(json.dumps(row['analysis']['status']), text)

    def test_outcomes_prices_and_unknown_payloads_are_not_forwarded(self):
        for market in self.bundle['underlying_markets']:
            market.update(last_price='FORBIDDEN-PRICE', result='FORBIDDEN-RESULT', private_note='FORBIDDEN-SECRET')
        self.bundle['combo_market']['private_note'] = 'FORBIDDEN-COMBO'
        self.page['data'][0]['home_score'] = 'FORBIDDEN-SCORE'
        text = json.dumps(self.report())
        self.assertNotIn('FORBIDDEN', text)

    def test_summary_escapes_source_text_and_control_characters(self):
        self.bundle['underlying_markets'][0]['rules_primary'] = '\x1b[2J\nunsafe text'
        text = service().consolidated_summary(self.report())
        self.assertNotIn('\x1b', text)
        self.assertIn('\\u001b', text)

    def test_invalid_cutoff_is_rejected_before_constructing_live_transport(self):
        from sportsiq.parlay_report import main
        err = StringIO()
        with patch('sportsiq.parlay_report.KalshiClient', side_effect=AssertionError('transport constructed')), \
                redirect_stderr(err), self.assertRaises(SystemExit) as caught:
            main(['--url', URL, '--live', '--cutoff', '2026-10-19'])
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn('Traceback', err.getvalue())

    def test_explicit_live_flag_reuses_existing_get_only_two_request_client(self):
        from sportsiq import parlay_report
        from sportsiq.providers.kalshi import KalshiClient

        class Transport:
            def __init__(self, bundle):
                self.requests = []
                self.responses = [{'market': bundle['combo_market']}, {'markets': bundle['underlying_markets']}]

            def open(self, request, **kwargs):
                self.requests.append(request)
                return BytesIO(json.dumps(self.responses.pop(0)).encode())

        # Replay saved field projections through the actual existing transport/client.
        transport = Transport(self.bundle)
        client = KalshiClient(transport=transport, max_retries=0, max_requests=2)
        out = StringIO()
        with patch.object(parlay_report, 'KalshiClient', return_value=client) as constructor, redirect_stdout(out):
            self.assertEqual(parlay_report.main(['--url', URL, '--live', '--snapshot', str(ROOT / 'missing-snapshot')]), 0)
        constructor.assert_called_once_with(max_retries=0, max_requests=2)
        self.assertEqual(len(transport.requests), 2)
        for request in transport.requests:
            self.assertEqual(request.get_method(), 'GET')
            self.assertTrue(request.full_url.startswith('https://external-api.kalshi.com/trade-api/v2/markets'))
            self.assertFalse(request.has_header('Authorization'))
        result = json.loads(out.getvalue())
        self.assertEqual(result['provenance']['market']['mode'], 'live')
        self.assertEqual(result['provenance']['market']['requests_made_this_run'], 2)
        self.assertEqual(result['leg_count'], 12)

    def test_raw_extractor_bundle_and_separate_games_file_are_supported(self):
        from sportsiq.parlay_report import main
        case = self.snapshot()
        path = case.path / 'raw.json'
        path.write_text(json.dumps(self.bundle))
        games = case.path / 'games.json'
        games.write_text(json.dumps(self.page))
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(['--url', URL, '--offline', str(path), '--games', str(games),
                                   '--snapshot', str(case.path / 'absent')]), 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result['leg_count'], 12)
        self.assertIsNone(result['provenance']['market']['captured_at'])
        self.assertEqual(result['provenance']['schedule']['reference'], games.as_uri())
        self.assertEqual(result['legs'][-1]['mapping']['outcome'], 'MATCHED')

    def test_cli_rejects_incomplete_inputs_with_no_partial_output_or_source_echo(self):
        from sportsiq.parlay_report import main
        case = self.snapshot()
        path = case.path / 'incomplete.json'
        self.bundle['underlying_markets'].pop()
        self.bundle['private_note'] = 'DO-NOT-ECHO'
        path.write_text(json.dumps(self.bundle))
        for fmt in ('json', 'summary'):
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as caught:
                main(['--url', URL, '--offline', str(path), '--format', fmt])
            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('DO-NOT-ECHO', err.getvalue())
            self.assertNotIn('Traceback', err.getvalue())
