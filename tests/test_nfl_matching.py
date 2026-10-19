"""Synthetic fixtures: no outcomes, paid endpoints, or network requests."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from sportsiq.domain.models import GameStatus, League
from sportsiq.domain.parlay import ParlayLeg
from sportsiq.providers.balldontlie import BALLDONTLIEGamesProvider


class NFLMatchingTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((Path(__file__).parent / 'fixtures/nfl_matching.json').read_text())
        self.leg = ParlayLeg(1, self.data['event_ticker'], self.data['market_ticker'],
                             'yes', 'nfl', 'event_ticker.series:KXNFLGAME', 'Los Angeles R',
                             'Los Angeles R wins', self.data['rules_primary'], {}, [],
                             {'event_ticker': self.data['event_ticker'], 'market_ticker': self.data['market_ticker'], 'side': 'yes'},
                             {**{k: self.data[k] for k in ('yes_sub_title', 'no_sub_title', 'rules_primary')},
                              'event_ticker': self.data['event_ticker'], 'ticker': self.data['market_ticker']}, None)
        self.game = BALLDONTLIEGamesProvider(League.NFL, None)._normalize(self.data['games'][0])

    def match(self, leg=None, games=None, **kwargs):
        from sportsiq.matching.nfl import match_nfl_leg
        return match_nfl_leg(leg or self.leg, [self.game] if games is None else games, **kwargs)

    def test_exact_pair_date_and_alias_match_preserves_evidence(self):
        result = self.match()
        self.assertEqual(result.outcome, 'MATCHED')
        self.assertEqual(result.game['provider_ids'], {'balldontlie': '900001'})
        self.assertEqual(result.event_ticker, self.leg.event_ticker)
        self.assertEqual(result.market_ticker, self.leg.market_ticker)
        self.assertEqual(result.evidence['rules_primary'], self.leg.description)
        self.assertEqual(result.evidence['teams'], ['ARI', 'LAR'])
        self.assertEqual(result.game['start_time'], '2026-10-18T20:05:00+00:00')
        self.assertIn('historical_kickoff_unverified', result.uncertainty)
        self.assertIsNone(result.game['verified_historical_kickoff'])

    def test_aliases_and_known_provider_ids_must_agree(self):
        from sportsiq.matching.nfl import canonical_team
        self.assertEqual(canonical_team('  LA Rams  '), 'LAR')
        self.assertEqual(canonical_team('WSH'), 'WAS')
        self.assertIsNone(canonical_team('Los Angeles'))
        self.assertIsNone(canonical_team('NY'))
        self.assertEqual(self.match(team_ids={'LAR': '9001', 'ARI': '9002'}).outcome, 'MATCHED')
        result = self.match(team_ids={'LAR': 'wrong'})
        self.assertEqual(result.outcome, 'NOT_FOUND')
        self.assertIn('provider identity conflict', result.uncertainty)

    def test_conflicting_provider_abbreviation_is_not_ignored(self):
        bad = replace(self.game, home=replace(self.game.home, abbreviation='SF'))
        self.assertEqual(self.match(games=[bad]).outcome, 'NOT_FOUND')

    def test_postponed_and_rescheduled_games_never_silently_match(self):
        postponed = replace(self.game, status=GameStatus.POSTPONED)
        result = self.match(games=[postponed])
        self.assertEqual(result.outcome, 'AMBIGUOUS')
        self.assertIsNone(result.game)
        moved = replace(postponed, start_time=datetime(2026, 10, 19, 20, tzinfo=timezone.utc))
        result = self.match(games=[moved])
        self.assertEqual(result.outcome, 'NOT_FOUND')
        self.assertIn('original/provider date conflict', result.uncertainty)
        self.assertEqual(result.evidence['rejected_games'][0]['provider_ids'], moved.provider_ids)

    def test_scheduled_timestamp_conflicts_and_naive_times_fail_closed(self):
        for value in ('2026-10-18T21:05:00Z', '2026-10-18T20:05:00', 'invalid'):
            with self.subTest(value=value):
                leg = replace(self.leg, times={'scheduled_start': {'value': value, 'source': 'milestone.start_date'}})
                self.assertEqual(self.match(leg).outcome, 'NOT_FOUND')

    def test_raw_milestone_start_must_corroborate_flattened_schedule(self):
        raw = {'start_date': '2026-10-19T20:05:00Z',
               'related_event_tickers': [self.leg.event_ticker]}
        leg = replace(self.leg, raw_milestone=raw, times={'scheduled_start': {
            'value': '2026-10-18T20:05:00Z', 'source': 'milestone.start_date'}})
        result = self.match(leg)
        self.assertEqual(result.outcome, 'UNSUPPORTED')
        self.assertIn('conflicting milestone scheduled start evidence', result.uncertainty)
        self.assertEqual(result.evidence['raw_milestone'], raw)
        self.assertEqual(result.evidence['source_times']['scheduled_start'], leg.times['scheduled_start'])
        self.assertIsNone(result.game)

    def test_raw_milestone_start_is_not_ignored_without_flattened_schedule(self):
        for times in ({}, {'scheduled_start': None}):
            for value in ('2026-10-19T20:05:00Z', 'invalid', '2026-10-18T20:05:00'):
                with self.subTest(times=times, value=value):
                    raw = {'start_date': value, 'related_event_tickers': [self.leg.event_ticker]}
                    result = self.match(replace(self.leg, raw_milestone=raw, times=times))
                    self.assertEqual(result.outcome, 'NOT_FOUND')
                    self.assertEqual(result.evidence['raw_milestone'], raw)
                    self.assertIsNone(result.game)
                    self.assertTrue(any('scheduled' in reason for reason in result.uncertainty))

    def test_supplied_milestone_must_identify_the_leg_event(self):
        for identities in ({}, {'related_event_tickers': []},
                           {'related_event_tickers': ['KXNFLGAME-OTHER']},
                           {'primary_event_tickers': ['KXNFLGAME-OTHER']}):
            with self.subTest(identities=identities):
                raw = {'start_date': '2026-10-18T20:05:00Z', **identities}
                result = self.match(replace(self.leg, raw_milestone=raw))
                self.assertEqual(result.outcome, 'UNSUPPORTED')
                self.assertIn('conflicting or missing milestone event identity', result.uncertainty)
                self.assertEqual(result.evidence['raw_milestone'], raw)

    def test_consistent_raw_start_accepts_equivalent_offsets_or_missing_flattening(self):
        raw = {'start_date': '2026-10-18T16:05:00-04:00',
               'primary_event_tickers': [self.leg.event_ticker]}
        flattened = {'value': '2026-10-18T20:05:00Z', 'source': 'milestone.start_date'}
        for times in ({}, {'scheduled_start': None}, {'scheduled_start': flattened}):
            with self.subTest(times=times):
                result = self.match(replace(self.leg, raw_milestone=raw, times=times))
                self.assertEqual(result.outcome, 'MATCHED')
                self.assertIsNone(result.game['verified_historical_kickoff'])
                self.assertEqual(result.evidence['raw_milestone'], raw)
        self.assertEqual(self.match(replace(self.leg, times={'scheduled_start': flattened})).outcome,
                         'MATCHED')

    def test_selection_and_yes_proposition_cannot_disagree(self):
        market = {**self.leg.raw_market, 'yes_sub_title': 'San Francisco'}
        self.assertEqual(self.match(replace(self.leg, raw_market=market)).outcome, 'UNSUPPORTED')

    def test_multiple_games_are_ambiguous_and_preserve_candidate_ids(self):
        other = replace(self.game, provider_ids={'balldontlie': '900003'})
        result = self.match(games=[self.game, other])
        self.assertEqual(result.outcome, 'AMBIGUOUS')
        self.assertIsNone(result.game)
        self.assertEqual(len(result.candidates), 2)

    def test_no_is_not_an_opponent_pick_and_outcomes_are_ignored(self):
        leg = replace(self.leg, side='no', raw_selection={**self.leg.raw_selection, 'side': 'no'},
                      raw_market={**self.leg.raw_market, 'result': 'yes', 'last_price': 99})
        result = self.match(leg)
        self.assertEqual(result.outcome, 'MATCHED')
        self.assertEqual(result.side, 'no')
        self.assertEqual(result.selection, 'Los Angeles R')
        self.assertEqual(result.evidence['proposition_team'], 'LAR')
        self.assertNotIn('result', result.evidence)

    def test_team_name_alone_or_wrong_opponent_never_matches(self):
        self.assertEqual(self.match(games=[]).outcome, 'NOT_FOUND')
        wrong = replace(self.game, away=replace(self.game.away, name='San Francisco 49ers', abbreviation='SF'))
        self.assertEqual(self.match(games=[wrong]).outcome, 'NOT_FOUND')
        self.assertEqual(self.match(replace(self.leg, description='Los Angeles R wins')).outcome, 'UNSUPPORTED')

    def test_home_away_is_enforced_only_for_explicit_at(self):
        rule = self.leg.description.replace(' vs ', ' at ')
        leg = replace(self.leg, description=rule, raw_market={**self.leg.raw_market, 'rules_primary': rule})
        self.assertEqual(self.match(leg).outcome, 'MATCHED')
        reversed_game = replace(self.game, home=self.game.away, away=self.game.home)
        self.assertEqual(self.match(leg, [reversed_game]).outcome, 'NOT_FOUND')
        self.assertEqual(self.match(games=[reversed_game]).outcome, 'MATCHED')

    def test_utc_rollover_uses_eastern_calendar_date_not_utc_date(self):
        game = replace(self.game, start_time=datetime(2026, 10, 19, 0, 15, tzinfo=timezone.utc))
        result = self.match(games=[game])
        self.assertEqual(result.outcome, 'MATCHED')
        self.assertEqual(result.game['start_time_eastern'], '2026-10-18T20:15:00-04:00')

    def test_occurrence_is_not_kickoff_or_a_matching_time_constraint(self):
        leg = replace(self.leg, times={'occurrence': {'value': '2026-10-19T03:00:00Z', 'source': 'market.occurrence_datetime'}})
        result = self.match(leg)
        self.assertEqual(result.outcome, 'MATCHED')
        self.assertEqual(result.game['start_time'], self.game.start_time.isoformat())
        self.assertIsNone(result.game['verified_historical_kickoff'])

    def test_college_and_other_series_are_unsupported(self):
        self.assertEqual(self.match(replace(self.leg, league='ncaaf')).outcome, 'UNSUPPORTED')
        self.assertEqual(self.match(replace(self.leg, event_ticker='KXNFLGAMEFAKE-EXAMPLE')).outcome, 'UNSUPPORTED')

    def test_occurrence_schedule_disagreement_is_explicit_not_a_kickoff_conflict(self):
        leg = replace(self.leg, times={'occurrence': {'value': '2026-10-18T23:05:00Z', 'source': 'market.occurrence_datetime'}})
        result = self.match(leg)
        self.assertEqual(result.outcome, 'MATCHED')
        self.assertIn('occurrence differs from provider schedule; occurrence is not kickoff', result.uncertainty)

    def test_source_conflicts_and_missing_identities_never_match(self):
        variants = [replace(self.leg, description=self.leg.description.replace('Oct 18', 'Oct 19')),
                    replace(self.leg, selection='Arizona'),
                    replace(self.leg, raw_selection={}),
                    replace(self.leg, raw_market={k: v for k, v in self.leg.raw_market.items() if k != 'ticker'})]
        for field, keys in (('raw_market', ('ticker', 'event_ticker', 'rules_primary')),
                            ('raw_selection', ('side', 'event_ticker', 'market_ticker'))):
            for key in keys:
                variants.append(replace(self.leg, **{field: {**getattr(self.leg, field), key: 'conflict'}}))
        for leg in variants:
            with self.subTest(leg=leg):
                result = self.match(leg)
                self.assertEqual(result.outcome, 'UNSUPPORTED')
                self.assertIn('conflicting or missing source evidence', result.uncertainty)

    def test_direct_consumers_reject_malformed_scheduled_evidence(self):
        with self.assertRaises(ValueError):
            self.match(replace(self.leg, times={'scheduled_start': {}}))

    def test_outcome_free_source_evidence_and_original_provider_date_roundtrip(self):
        from dataclasses import asdict
        original = '2026-10-18T16:05:00.000000-04:00'
        raw_game = {**self.data['games'][0], 'date': original, 'home_score': 42, 'result': 'win'}
        raw_market = {**self.leg.raw_market, 'custom_strike': {'football_team': 'uuid', 'price': 90},
                      'occurrence_datetime': original, 'last_price': 90, 'result': 'yes'}
        milestone = {'id': 'milestone', 'start_date': original, 'last_updated_ts': original,
                     'related_event_tickers': [self.leg.event_ticker], 'result': 'win'}
        leg = replace(self.leg, raw_market=raw_market, raw_milestone=milestone, gaps=['missing_actual_start_time'],
                      times={'occurrence': {'value': original, 'source': 'market.occurrence_datetime', 'result': 'yes'},
                             'last_price': {'value': '90', 'source': 'price'}})
        result = self.match(leg, source_games={'900001': raw_game})
        evidence = json.loads(json.dumps(asdict(result)))['evidence']
        self.assertEqual(evidence['raw_selection'], self.leg.raw_selection)
        self.assertEqual(evidence['raw_milestone']['start_date'], original)
        self.assertEqual(evidence['gaps'], leg.gaps)
        self.assertEqual(evidence['raw_market']['occurrence_datetime'], original)
        self.assertEqual(evidence['raw_market']['custom_strike'], {'football_team': 'uuid'})
        self.assertEqual(result.game['source_record']['date'], original)
        serialized = json.dumps(asdict(result))
        for forbidden in ('last_price', 'home_score', '"result"', '"price"'):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(self.match().game['source_evidence_gap'], 'raw provider record not supplied')
        conflict = replace(leg, raw_market={**raw_market, 'ticker': 'conflict'})
        self.assertEqual(self.match(conflict).evidence['raw_market']['ticker'], 'conflict')

    def test_rejected_identity_candidates_preserve_ids_and_source(self):
        result = self.match(team_ids={'LAR': 'wrong'}, source_games={'900001': self.data['games'][0]})
        rejected = result.evidence['rejected_games'][0]
        self.assertEqual(rejected['provider_ids'], {'balldontlie': '900001'})
        self.assertEqual(rejected['home']['provider_ids'], {'balldontlie': '9001'})
        self.assertEqual(rejected['source_record']['date'], self.data['games'][0]['date'])
        self.assertEqual(rejected['rejection_reason'], 'provider identity conflict')

    def test_observed_combo_projection_has_twelve_legs_and_two_exact_nfl_matches(self):
        from sportsiq.matching.nfl import match_nfl_leg
        data = json.loads((Path(__file__).parent / 'fixtures/nfl_combo_observed.json').read_text())
        extraction = data['extraction']
        games = [BALLDONTLIEGamesProvider(League.NFL, None)._normalize(g) for g in data['games_page']['data']]
        legs = [ParlayLeg(**leg) for leg in extraction['legs']]
        sources = {str(g['id']): g for g in data['games_page']['data']}
        results = [match_nfl_leg(leg, games, source_games=sources) for leg in legs]
        self.assertEqual(extraction['leg_count'], len(results))
        self.assertEqual(len(results), 12)
        self.assertEqual([r.outcome for r in results], ['UNSUPPORTED'] * 10 + ['MATCHED'] * 2)
        self.assertEqual([r.game['provider_ids']['balldontlie'] for r in results[-2:]], ['1392304', '1392308'])
        self.assertEqual([r.side for r in results], ['yes'] * 12)
        for leg, result in zip(legs, results):
            self.assertEqual(result.evidence['raw_selection'], leg.raw_selection)
            self.assertEqual(result.evidence['raw_market'], leg.raw_market)
            self.assertEqual(result.evidence['raw_milestone'], leg.raw_milestone)
            self.assertEqual(result.evidence['gaps'], leg.gaps)
        for result in results[-2:]:
            self.assertEqual(result.game['source_record']['date'], sources[result.game['provider_ids']['balldontlie']]['date'])
            self.assertIn('occurrence differs from provider schedule; occurrence is not kickoff', result.uncertainty)
