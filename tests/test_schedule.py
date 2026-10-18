import json
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

from sportsiq.domain.models import Game, Team
from sportsiq.providers.espn_nfl import ESPNNFLScheduleProvider
from sportsiq.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "nfl_scoreboard.json"


class NFLFixtureScheduleTests(unittest.TestCase):
    def test_normalizes_game_with_aware_utc_start_and_provider_ids(self):
        source = Mock()
        source.get_scoreboard.return_value = json.loads(FIXTURE.read_text())
        provider = ESPNNFLScheduleProvider(source)

        games = provider.games_on(date(2026, 9, 13))

        self.assertEqual(len(games), 1)
        game = games[0]
        self.assertEqual(game.provider_ids, {"espn": "synthetic-game-101"})
        self.assertEqual(game.home.provider_ids, {"espn": "synthetic-team-home"})
        self.assertEqual(game.away.name, "Example Away")
        self.assertEqual(game.start_time.utcoffset(), timezone.utc.utcoffset(None))
        source.get_scoreboard.assert_called_once_with(date(2026, 9, 13))

    def test_rejects_a_start_time_without_timezone(self):
        payload = json.loads(FIXTURE.read_text())
        payload["events"][0]["date"] = "2026-09-13T17:00:00"
        source = Mock()
        source.get_scoreboard.return_value = payload

        with self.assertRaisesRegex(ValueError, "timezone"):
            ESPNNFLScheduleProvider(source).games_on(date(2026, 9, 13))

    def test_normalizes_offset_start_to_utc(self):
        payload = json.loads(FIXTURE.read_text())
        payload["events"][0]["date"] = "2026-09-13T13:00:00-04:00"
        source = Mock()
        source.get_scoreboard.return_value = payload

        game = ESPNNFLScheduleProvider(source).games_on(date(2026, 9, 13))[0]

        self.assertEqual(game.start_time.isoformat(), "2026-09-13T17:00:00+00:00")

    def test_game_rejects_naive_start_time(self):
        team = Team("Example", {"espn": "test-team"})
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            Game(team, team, datetime(2026, 9, 13, 17), {"espn": "test-game"})

    def test_cli_queries_fixture_without_network_and_prints_normalized_json(self):
        output = StringIO()
        with redirect_stdout(output):
            result = main(["schedule", "--date", "2026-09-13", "--fixture", str(FIXTURE)])

        self.assertEqual(result, 0)
        games = json.loads(output.getvalue())
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["start_time"], "2026-09-13T17:00:00+00:00")
        self.assertEqual(games[0]["provider_ids"], {"espn": "synthetic-game-101"})


if __name__ == "__main__":
    unittest.main()
