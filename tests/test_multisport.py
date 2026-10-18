import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from sportsiq.domain.models import Game, GameStatus, League, Team
from sportsiq.providers.espn_nfl import ESPNNFLScheduleProvider


class MultiSportModelTests(unittest.TestCase):
    def test_game_carries_explicit_league_status_and_string_provider_ids(self):
        home = Team("Example Home", {"balldontlie": "11"}, abbreviation="HOM")
        away = Team("Example Away", {"balldontlie": "12"})
        game = Game(
            home, away, datetime(2026, 10, 21, tzinfo=timezone.utc),
            {"balldontlie": "99"}, league=League.NBA, status=GameStatus.SCHEDULED,
        )

        self.assertEqual(game.league, League.NBA)
        self.assertEqual(game.status, GameStatus.SCHEDULED)
        self.assertEqual(game.home.abbreviation, "HOM")
        self.assertEqual(game.provider_ids, {"balldontlie": "99"})

    def test_nfl_fixture_parser_maps_explicit_pregame_status(self):
        source = Mock()
        source.get_scoreboard.return_value = {"events": [{
            "id": "synthetic-nfl-game", "date": "2026-09-13T17:00:00Z",
            "status": {"type": {"state": "pre"}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"id": "1", "displayName": "Home"}},
                {"homeAway": "away", "team": {"id": "2", "displayName": "Away"}},
            ]}],
        }]}

        game = ESPNNFLScheduleProvider(source).games_on(date(2026, 9, 13))[0]

        self.assertEqual(game.league, League.NFL)
        self.assertEqual(game.status, GameStatus.SCHEDULED)

    def test_nfl_special_status_overrides_broad_state(self):
        fixture = Path(__file__).parent / "fixtures" / "nfl_scoreboard.json"
        for name, state, expected in (
            ("STATUS_POSTPONED", "pre", GameStatus.POSTPONED),
            ("STATUS_CANCELED", "post", GameStatus.CANCELED),
            ("STATUS_SCHEDULED", "pre", GameStatus.SCHEDULED),
            ("STATUS_IN_PROGRESS", "in", GameStatus.IN_PROGRESS),
            ("STATUS_FINAL", "post", GameStatus.FINAL),
            ("STATUS_DELAYED", "pre", GameStatus.DELAYED),
            ("STATUS_SUSPENDED", "in", GameStatus.SUSPENDED),
            ("STATUS_UNRECOGNIZED", "pre", GameStatus.UNKNOWN),
        ):
            with self.subTest(name=name):
                payload = json.loads(fixture.read_text())
                payload["events"][0]["status"] = {"type": {"name": name, "state": state}}
                source = Mock()
                source.get_scoreboard.return_value = payload
                game = ESPNNFLScheduleProvider(source).games_on(date(2026, 9, 13))[0]
                self.assertEqual(game.status, expected)


if __name__ == "__main__":
    unittest.main()
