import json
import unittest
from contextlib import redirect_stdout
from datetime import date, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

from sportsiq.cli import main
from sportsiq.domain.models import GameStatus, League
from sportsiq.providers.nba_schedule import NBAFixtureScheduleProvider


FIXTURE = Path(__file__).parent / "fixtures" / "nba_games.json"


class NBAFixtureScheduleTests(unittest.TestCase):
    def test_normalizes_league_status_ids_and_utc_boundary(self):
        source = Mock()
        source.get_schedule.return_value = json.loads(FIXTURE.read_text())

        games = NBAFixtureScheduleProvider(source).games_on(date(2026, 10, 21))

        self.assertEqual(len(games), 1)
        game = games[0]
        self.assertEqual(game.league, League.NBA)
        self.assertEqual(game.status, GameStatus.SCHEDULED)
        self.assertEqual(game.provider_ids, {"balldontlie": "900001"})
        self.assertEqual(game.home.provider_ids, {"balldontlie": "101"})
        self.assertEqual(game.away.provider_ids, {"balldontlie": "102"})
        self.assertEqual(game.home.abbreviation, "EHB")
        self.assertEqual(game.start_time.isoformat(), "2026-10-21T03:30:00+00:00")
        self.assertEqual(game.start_time.tzinfo, timezone.utc)
        source.get_schedule.assert_called_once_with(date(2026, 10, 21))

    def test_rejects_naive_nba_fixture_start(self):
        payload = json.loads(FIXTURE.read_text())
        payload["data"][0]["datetime"] = "2026-10-20T23:30:00"
        source = Mock()
        source.get_schedule.return_value = payload

        with self.assertRaisesRegex(ValueError, "timezone"):
            NBAFixtureScheduleProvider(source).games_on(date(2026, 10, 20))

    def test_missing_nba_tipoff_is_rejected_without_guessing(self):
        payload = json.loads(FIXTURE.read_text())
        payload["data"][0]["datetime"] = None
        source = Mock()
        source.get_schedule.return_value = payload

        with self.assertRaisesRegex(ValueError, "tipoff"):
            NBAFixtureScheduleProvider(source).games_on(date(2026, 10, 21))

    def test_cli_queries_nba_fixture_as_json(self):
        output = StringIO()
        with redirect_stdout(output):
            result = main(["schedule", "--league", "nba", "--date", "2026-10-21",
                           "--fixture", str(FIXTURE)])

        self.assertEqual(result, 0)
        games = json.loads(output.getvalue())
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["league"], "nba")
        self.assertEqual(games[0]["status"], "scheduled")
        self.assertEqual(games[0]["start_time"], "2026-10-21T03:30:00+00:00")
        self.assertEqual(games[0]["provider_ids"], {"balldontlie": "900001"})


if __name__ == "__main__":
    unittest.main()
