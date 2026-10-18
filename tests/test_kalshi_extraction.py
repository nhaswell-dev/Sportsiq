"""Synthetic extraction cases; no historical observations are fabricated."""
from copy import deepcopy
from dataclasses import asdict
import unittest

from test_kalshi import EVENT, MARKET, URL


def bundle(count=1, series="KXNCAAFGAME"):
    legs = [{"event_ticker": f"{series}-26OCT17TEST{i}",
             "market_ticker": f"{series}-26OCT17TEST{i}-HOME", "side": "yes"} for i in range(count)]
    return {"fixture_kind": "synthetic", "combo_market": {
        "ticker": MARKET, "event_ticker": EVENT, "title": "Synthetic combo",
        "mve_selected_legs": legs, "extra_provider_field": {"keep": True}},
        "underlying_markets": [{"ticker": leg["market_ticker"], "event_ticker": leg["event_ticker"],
            "title": "Synthetic home wins", "yes_sub_title": "Synthetic Home", "no_sub_title": "Not home",
            "rules_primary": "Synthetic home wins the synthetic game.",
            "occurrence_datetime": "2026-10-17T20:00:00Z", "updated_time": "2026-10-18T01:00:00Z"}
            for leg in legs]}


class ExtractionTests(unittest.TestCase):
    def extract(self, data):
        from sportsiq.providers.kalshi import extract_parlay, parse_kalshi_url
        return asdict(extract_parlay(parse_kalshi_url(URL), data, source="offline"))

    def test_extracts_selection_and_preserves_metadata_without_inventing_times(self):
        data = bundle()
        before = deepcopy(data)
        result = self.extract(data)
        self.assertEqual(result["market_ticker"], MARKET)
        self.assertEqual(result["leg_count"], 1)
        leg = result["legs"][0]
        self.assertEqual((leg["league"], leg["side"], leg["selection"]), ("ncaaf", "yes", "Synthetic Home"))
        self.assertEqual(leg["description"], data["underlying_markets"][0]["rules_primary"])
        self.assertEqual(leg["times"]["occurrence"]["value"], "2026-10-17T20:00:00Z")
        self.assertIsNone(leg["times"]["scheduled_start"])
        self.assertIsNone(leg["times"]["actual_start"])
        self.assertEqual(result["raw_combo_market"], data["combo_market"])
        self.assertEqual(leg["raw_market"], data["underlying_markets"][0])
        self.assertEqual(data, before)

    def test_no_side_unknown_league_and_incomplete_descriptions(self):
        data = bundle(series="KXNHLGAME")
        data["combo_market"]["mve_selected_legs"][0]["side"] = "no"
        data["underlying_markets"][0] = {k: v for k, v in data["underlying_markets"][0].items()
                                         if k in ("ticker", "event_ticker")}
        leg = self.extract(data)["legs"][0]
        self.assertEqual(leg["league"], "unsupported")
        self.assertEqual(leg["side"], "no")
        self.assertIsNone(leg["selection"])
        self.assertIsNone(leg["description"])
        self.assertIn("missing_selection_label", leg["gaps"])
        self.assertIn("unsupported_league", leg["gaps"])

    def test_supported_leagues_use_exact_series_not_title_guesses(self):
        for series, expected in (("KXNFLGAME", "nfl"), ("KXNBAGAME", "nba"),
                                 ("KXNCAAFGAME", "ncaaf"), ("KXNCAABGAME", "ncaab"),
                                 ("KXNCAAFGAMEFAKE", "unsupported")):
            with self.subTest(series=series):
                self.assertEqual(self.extract(bundle(series=series))["legs"][0]["league"], expected)

    def test_duplicate_or_invalid_legs_fail_closed(self):
        from sportsiq.providers.kalshi import KalshiError
        for mutate in (
            lambda d: d["combo_market"]["mve_selected_legs"].append(deepcopy(d["combo_market"]["mve_selected_legs"][0])),
            lambda d: d["combo_market"]["mve_selected_legs"][0].update(side="YES"),
            lambda d: d["combo_market"]["mve_selected_legs"][0].pop("event_ticker"),
            lambda d: d["underlying_markets"].clear(),
            lambda d: d["underlying_markets"][0].update(event_ticker="OTHER-EVENT"),
            lambda d: d["combo_market"].update(event_ticker="OTHER-EVENT"),
        ):
            data = bundle()
            mutate(data)
            with self.assertRaises(KalshiError):
                self.extract(data)

    def test_46_legs_preserve_api_order_and_all_selections(self):
        data = bundle(46)
        data["underlying_markets"].reverse()
        result = self.extract(data)
        self.assertEqual(result["leg_count"], 46)
        self.assertEqual([r["market_ticker"] for r in result["legs"]],
                         [r["market_ticker"] for r in data["combo_market"]["mve_selected_legs"]])
        self.assertEqual(len({r["market_ticker"] for r in result["legs"]}), 46)

    def test_optional_milestone_times_remain_distinct_and_conflicts_are_flagged(self):
        data = bundle()
        event = data["combo_market"]["mve_selected_legs"][0]["event_ticker"]
        data["milestones"] = [{"related_event_tickers": [event], "start_date": "2026-10-17T17:00:00Z",
                               "last_updated_ts": "2026-10-18T01:00:00Z",
                               "details": {"status": "final"}, "end_date": "2026-10-17T21:00:00Z"}]
        leg = self.extract(data)["legs"][0]
        self.assertEqual(leg["times"]["scheduled_start"]["value"], "2026-10-17T17:00:00Z")
        self.assertEqual(leg["times"]["schedule_updated"]["value"], "2026-10-18T01:00:00Z")
        self.assertIsNone(leg["times"]["actual_start"])
        self.assertIn("scheduled_occurrence_mismatch", leg["gaps"])
        self.assertIn("pregame_availability_unverified", leg["gaps"])
        self.assertEqual(leg["raw_milestone"], data["milestones"][0])

    def test_invalid_time_is_retained_raw_not_normalized_into_kickoff(self):
        data = bundle()
        data["underlying_markets"][0]["occurrence_datetime"] = "2026-10-17T12:00:00"
        leg = self.extract(data)["legs"][0]
        self.assertIsNone(leg["times"]["occurrence"])
        self.assertIn("invalid_occurrence_time", leg["gaps"])
        self.assertEqual(leg["raw_market"]["occurrence_datetime"], "2026-10-17T12:00:00")

    def test_explicit_actual_start_is_not_occurrence_or_schedule(self):
        data = bundle()
        event = data["combo_market"]["mve_selected_legs"][0]["event_ticker"]
        data["milestones"] = [{"primary_event_tickers": [event],
                               "start_date": "2026-10-17T16:00:00-04:00",
                               "actual_start_time": "2026-10-17T20:03:00Z"}]
        leg = self.extract(data)["legs"][0]
        self.assertEqual(leg["times"]["actual_start"]["value"], "2026-10-17T20:03:00Z")
        self.assertNotIn("scheduled_occurrence_mismatch", leg["gaps"])
        data["milestones"].append(deepcopy(data["milestones"][0]))
        from sportsiq.providers.kalshi import KalshiError
        with self.assertRaisesRegex(KalshiError, "ambiguous"):
            self.extract(data)

    def test_raw_records_are_copied_and_no_selection_never_invents_opponent(self):
        data = bundle()
        data["combo_market"]["mve_selected_legs"][0]["side"] = "no"
        data["underlying_markets"][0]["no_sub_title"] = "Synthetic Home"
        result = self.extract(data)
        data["underlying_markets"][0]["title"] = "changed"
        self.assertEqual(result["legs"][0]["title"], "Synthetic home wins")
        self.assertEqual(result["legs"][0]["selection"], "Synthetic Home")
        self.assertEqual(result["legs"][0]["side"], "no")
