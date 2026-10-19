"""Offline matching CLI and report exercise real captured-extraction shape."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import test_nfl_matching


class MatchingCLITests(unittest.TestCase):
    def test_summary_escapes_all_external_display_fields(self):
        from sportsiq.reports.nfl_matching import matching_summary
        case = test_nfl_matching.NFLMatchingTests()
        case.setUp()
        result = asdict(case.match())
        for key in ('side', 'league', 'outcome', 'event_ticker', 'selection'):
            result[key] += '\x1b[31m\n'
        report = matching_summary({'event_ticker': '\x1b[2J', 'leg_count': 1,
                                   'schedule_coverage': '\x1b[2J', 'matches': [result]})
        self.assertNotIn('\x1b', report)
        self.assertIn('\\u001b', report)

    def run_input(self, leg, fmt, *, source_games=None):
        from sportsiq.matching.__main__ import main
        case = test_nfl_matching.NFLMatchingTests()
        case.setUp()
        extraction = dict(source='offline', observed_at='unknown', original_url='synthetic',
                          event_ticker='COMBO', market_ticker='COMBO-M', leg_count=1, legs=[leg])
        out, err = StringIO(), StringIO()
        with TemporaryDirectory() as directory:
            extracted, games = Path(directory) / 'legs.json', Path(directory) / 'games.json'
            extracted.write_text(json.dumps(extraction))
            games.write_text(json.dumps({'data': case.data['games'] if source_games is None else source_games, 'meta': {}}))
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    code = main(['--extraction', str(extracted), '--games', str(games), '--format', fmt])
                except SystemExit as exc:
                    code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_duplicate_provider_game_ids_exit_two_sanitized(self):
        case = test_nfl_matching.NFLMatchingTests()
        case.setUp()
        original = case.data['games'][0]
        other = {**original, 'date': '2026-10-20T00:15:00Z',
                 'home_team': {'id': 9003, 'full_name': 'San Francisco 49ers', 'abbreviation': 'SF'},
                 'visitor_team': {'id': 9004, 'full_name': 'Washington Commanders', 'abbreviation': 'WAS'},
                 'private_note': '\x1b[31mDO-NOT-ECHO'}
        for duplicate in (original, other, {**other, 'id': str(original['id'])}):
            for fmt in ('json', 'summary'):
                with self.subTest(duplicate=duplicate, fmt=fmt):
                    code, out, err = self.run_input(asdict(case.leg), fmt,
                                                    source_games=[original, duplicate])
                    self.assertEqual(code, 2)
                    self.assertEqual(out, '')
                    self.assertIn('invalid extraction or NFL Games page', err)
                    self.assertNotIn('Traceback', err)
                    self.assertNotIn('DO-NOT-ECHO', err)
                    self.assertNotIn('\x1b', err)

    def test_distinct_provider_game_ids_preserve_the_correct_source(self):
        case = test_nfl_matching.NFLMatchingTests()
        case.setUp()
        original = case.data['games'][0]
        other = {**original, 'id': 900002, 'date': '2026-10-20T00:15:00Z',
                 'home_team': {'id': 9003, 'full_name': 'San Francisco 49ers', 'abbreviation': 'SF'},
                 'visitor_team': {'id': 9004, 'full_name': 'Washington Commanders', 'abbreviation': 'WAS'}}
        code, out, err = self.run_input(asdict(case.leg), 'json', source_games=[original, other])
        self.assertEqual(code, 0, err)
        match = json.loads(out)['matches'][0]
        self.assertEqual(match['outcome'], 'MATCHED')
        self.assertEqual(match['game']['source_record'], original)

    def test_raw_milestone_date_conflicts_cannot_match_in_either_format(self):
        case = test_nfl_matching.NFLMatchingTests()
        case.setUp()
        raw = {'start_date': '2026-10-19T20:05:00Z',
               'related_event_tickers': [case.leg.event_ticker]}
        for times, outcome in (({'scheduled_start': {'value': '2026-10-18T20:05:00Z',
                                                     'source': 'milestone.start_date'}}, 'UNSUPPORTED'),
                               ({}, 'NOT_FOUND'), ({'scheduled_start': None}, 'NOT_FOUND')):
            leg = {**asdict(case.leg), 'raw_milestone': raw, 'times': times}
            for fmt in ('json', 'summary'):
                with self.subTest(times=times, fmt=fmt):
                    code, out, err = self.run_input(leg, fmt)
                    self.assertEqual(code, 0, err)
                    if fmt == 'json':
                        match = json.loads(out)['matches'][0]
                        self.assertEqual(match['outcome'], outcome)
                        self.assertIsNone(match['game'])
                        self.assertEqual(match['evidence']['raw_milestone'], raw)
                        self.assertEqual(match['evidence']['source_times'], times)
                    else:
                        self.assertIn(outcome, out)
                        self.assertNotIn('MATCHED', out)

    def test_malformed_nested_shapes_exit_two_without_traceback(self):
        case = test_nfl_matching.NFLMatchingTests()
        case.setUp()
        mutations = [('raw_market', None), ('raw_selection', []), ('raw_milestone', []),
                     ('times', []), ('gaps', 'bad'), ('selection', {}), ('league', []),
                     ('position', True), ('raw_market', {'custom_strike': None}),
                     ('times', {'scheduled_start': {}}), ('times', {'occurrence': []}),
                     ('raw_milestone', {'related_event_tickers': None}),
                     ('raw_milestone', {'primary_event_tickers': 'not-an-array'}),
                     ('raw_milestone', {'actual_start_time': {}}),
                     ('raw_milestone', {'last_updated_ts': []}),
                     ('raw_market', {'created_time': {}})]
        for key, value in mutations:
            for fmt in ('json', 'summary'):
                with self.subTest(key=key, value=value, fmt=fmt):
                    code, out, err = self.run_input({**asdict(case.leg), key: value}, fmt)
                    self.assertEqual(code, 2)
                    self.assertEqual(out, '')
                    self.assertIn('invalid extraction or NFL Games page', err)
                    self.assertNotIn('Traceback', err)

    def test_invalid_occurrence_is_unknown_in_both_formats_including_unsupported(self):
        case = test_nfl_matching.NFLMatchingTests()
        case.setUp()
        for league, unmatched in (('nfl', False), ('ncaaf', False), ('nfl', True)):
            for value in ('invalid', '2026-10-18T20:05:00'):
                leg = {**asdict(case.leg), 'league': league,
                       'times': {'occurrence': {'value': value, 'source': 'market.occurrence_datetime'}}}
                if unmatched:
                    leg['times']['scheduled_start'] = {'value': '2026-10-18T21:05:00Z', 'source': 'milestone.start_date'}
                for fmt in ('json', 'summary'):
                    with self.subTest(league=league, value=value, fmt=fmt):
                        code, out, err = self.run_input(leg, fmt)
                        self.assertEqual(code, 0, err)
                        if fmt == 'json':
                            evidence = json.loads(out)['matches'][0]
                            self.assertIn('invalid occurrence metadata; not used for matching', evidence['uncertainty'])
                            self.assertEqual(evidence['evidence']['source_times']['occurrence']['value'], value)
                        elif league == 'ncaaf' or unmatched:
                            self.assertIn('occurrence unknown', out)
                            self.assertNotIn(' UTC / ', out)

    def test_offline_json_and_summary_preserve_every_leg_and_use_no_network(self):
        from sportsiq.matching.__main__ import main
        case = test_nfl_matching.NFLMatchingTests()
        case.setUp()
        extraction = {'source': 'offline', 'observed_at': '2026-10-19T12:00:00Z',
                      'original_url': 'synthetic', 'event_ticker': 'SYNTHETIC-EVENT',
                      'market_ticker': 'SYNTHETIC-MARKET', 'leg_count': 1,
                      'legs': [asdict(case.leg)]}
        with TemporaryDirectory() as directory:
            extracted = Path(directory) / 'extracted.json'
            games = Path(directory) / 'games.json'
            extracted.write_text(json.dumps(extraction))
            games.write_text(json.dumps({'data': case.data['games'], 'meta': {'next_cursor': None}}))
            for fmt in ('json', 'summary'):
                out = StringIO()
                with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')), redirect_stdout(out):
                    self.assertEqual(main(['--extraction', str(extracted), '--games', str(games), '--format', fmt]), 0)
                if fmt == 'json':
                    result = json.loads(out.getvalue())
                    self.assertEqual(len(result['matches']), 1)
                    self.assertEqual(result['matches'][0]['outcome'], 'MATCHED')
                    self.assertEqual(result['matches'][0]['game']['source_record']['date'], case.data['games'][0]['date'])
                    self.assertIsNone(result['matches'][0]['game']['source_evidence_gap'])
                    self.assertEqual(result['schedule_coverage'], 'supplied page only; not verified historical coverage')
                else:
                    self.assertIn('MATCHED', out.getvalue())
                    self.assertIn('2026-10-18T16:05:00-04:00', out.getvalue())
                    self.assertIn('Missing pregame', out.getvalue())
                    self.assertIn('market=KXNFLGAME-SYNTHETIC-LAR', out.getvalue())
            extraction['leg_count'] = 2
            extracted.write_text(json.dumps(extraction))
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                main(['--extraction', str(extracted), '--games', str(games)])
