import json
import sqlite3
import unittest
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sportsiq.cli import main
from sportsiq.domain.models import GameStatus
from sportsiq.storage.schedule import ScheduleStore


def record(league="nfl", identifier="synthetic-1"):
    return {
        "league": league, "provider_ids": {"balldontlie": identifier},
        "home": {"name": "Example Home", "provider_ids": {"balldontlie": "11"}, "abbreviation": "HOM"},
        "away": {"name": "Example Away", "provider_ids": {"balldontlie": "12"}, "abbreviation": "AWY"},
        "start_time": "2026-10-21T20:30:00-04:00", "status": "scheduled",
    }


class ScheduleStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "schedule.sqlite3"

    def test_persists_nfl_and_nba_with_source_scoped_identity(self):
        with ScheduleStore(self.path) as store:
            self.assertEqual(store.import_records([record(), record("nba")], "balldontlie",
                             retrieved_at="2026-10-18T12:00:00Z"), 2)
        with ScheduleStore(self.path) as store:
            games = store.query()
            self.assertEqual(len(games), 2)
            self.assertEqual({g["league"] for g in games}, {"nfl", "nba"})
            self.assertEqual(games[0]["start_time"], "2026-10-22T00:30:00.000000+00:00")
            self.assertEqual(games[0]["retrieved_at"], "2026-10-18T12:00:00.000000+00:00")
            self.assertEqual(games[0]["created_at"], games[0]["updated_at"])
            self.assertEqual(len(store.query(league="nfl", day="2026-10-22")), 1)
            self.assertEqual(store.query(day="2026-10-21"), [])
            self.assertEqual(store.query(provider="other"), [])

    def test_upsert_refreshes_observation_and_preserves_changes_and_cancellation(self):
        with ScheduleStore(self.path) as store:
            for league in ("nfl", "nba"):
                original = record(league)
                store.import_records([original], "balldontlie", retrieved_at="2026-10-18T12:00:00Z")
                before = store.query(league=league)[0]
                store.import_records([original], "balldontlie", retrieved_at="2026-10-18T13:00:00Z")
                refreshed = store.query(league=league)[0]
                self.assertEqual(refreshed["updated_at"], before["updated_at"])
                self.assertNotEqual(refreshed["retrieved_at"], before["retrieved_at"])
                changed = dict(original, start_time="2026-10-23T01:00:00Z", status="postponed")
                store.import_records([changed], "balldontlie", retrieved_at="2026-10-18T14:00:00Z")
                canceled = dict(changed, status="canceled")
                store.import_records([canceled], "balldontlie", retrieved_at="2026-10-18T15:00:00Z")
                after = store.query(league=league)[0]
                self.assertEqual(after["id"], before["id"])
                self.assertEqual(after["created_at"], before["created_at"])
                self.assertEqual(after["status"], "canceled")
                history = store.history(after["id"])
                self.assertEqual(len(history), 2)
                self.assertEqual(history[0]["before"]["start_time"], before["start_time"])
                self.assertEqual(history[0]["after"]["status"], "postponed")
                self.assertEqual(history[1]["before"]["status"], "postponed")
                self.assertEqual(history[1]["after"]["status"], "canceled")
                self.assertEqual(history[1]["retrieved_at"], after["retrieved_at"])
            self.assertEqual(len(store.query()), 2)
            with self.assertRaises(sqlite3.IntegrityError):
                columns = list(store.query()[0])
                columns.remove("id")
                names = ", ".join(columns)
                store.connection.execute(f"INSERT INTO games ({names}) SELECT {names} FROM games WHERE league = 'nfl'")

    def test_invalid_records_reject_whole_batch_with_clear_errors(self):
        cases = [
            ("provider_ids", {}, "provider_game_id"),
            ("provider_ids", {"balldontlie": None}, "provider_game_id"),
            ("provider_ids", {"balldontlie": 77}, "provider_game_id"),
            ("provider_ids", {"balldontlie": "  "}, "provider_game_id"),
            ("start_time", "not-a-date", "start_time"),
            ("start_time", "2026-02-30T00:00:00Z", "start_time"),
            ("start_time", "2026-10-21T01:00:00", "start_time"),
            ("start_time", None, "start_time"),
            ("status", "not-a-status", "status"),
            ("status", None, "status"),
            ("league", "mlb", "league"),
            ("home", None, "home"),
            ("away", {"name": "Away"}, "away"),
            ("home", {"name": " ", "provider_ids": {"balldontlie": "11"}}, "home"),
            ("away", {"name": "Away", "provider_ids": {"balldontlie": "12"}, "abbreviation": 12}, "away"),
        ]
        with ScheduleStore(self.path) as store:
            for field, value, message in cases:
                with self.subTest(field=field, value=value):
                    invalid = dict(record(), **{field: value})
                    with self.assertRaisesRegex(ValueError, "record 2.*" + message):
                        store.import_records([record(identifier="valid"), invalid], "balldontlie")
                    self.assertEqual(store.query(), [])
            for records in ({"data": []}, None, [None], [42]):
                with self.subTest(records=records), self.assertRaisesRegex(ValueError, "records|record 1"):
                    store.import_records(records, "balldontlie")
            for missing in ("status", "league", "start_time", "home", "provider_ids"):
                invalid = deepcopy(record())
                del invalid[missing]
                with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "record 1"):
                    store.import_records([invalid], "balldontlie")
            invalid = record()
            invalid["away"] = invalid["home"]
            with self.assertRaisesRegex(ValueError, "different"):
                store.import_records([invalid], "balldontlie")
            with self.assertRaisesRegex(ValueError, "provider"):
                store.import_records([record()], " ")
            with self.assertRaisesRegex(ValueError, "retrieved_at"):
                store.import_records([record()], "balldontlie", retrieved_at="bad")

    def test_older_observations_cannot_regress_current_state_or_freshness(self):
        with ScheduleStore(self.path) as store:
            store.import_records([record()], "balldontlie", retrieved_at="2026-10-18T14:00:00Z")
            before = store.query()
            with self.assertRaisesRegex(ValueError, "older"):
                store.import_records([record(identifier="new"), dict(record(), status="canceled")],
                                     "balldontlie", retrieved_at="2026-10-18T13:00:00Z")
            self.assertEqual(store.query(), before)
            self.assertEqual(store.history(before[0]["id"]), [])

    def test_staleness_uses_retrieval_time_not_start_time_with_strict_cutoff(self):
        with ScheduleStore(self.path) as store:
            store.import_records([record()], "balldontlie", retrieved_at="2026-10-18T10:00:00Z")
            store.import_records([record("nba")], "balldontlie", retrieved_at="2026-10-18T12:00:00Z")
            stale = store.stale(hours=2, now="2026-10-18T14:00:00Z")
            self.assertEqual([g["league"] for g in stale], ["nfl"])
            self.assertEqual(store.stale(hours=2, now="2026-10-18T14:00:00Z", league="nba"), [])
            store.import_records([record()], "balldontlie", retrieved_at="2026-10-18T13:00:00Z")
            self.assertEqual(store.stale(hours=2, now="2026-10-18T14:00:00Z"), [])
            for hours in (-1, float("nan"), float("inf")):
                with self.subTest(hours=hours), self.assertRaisesRegex(ValueError, "hours"):
                    store.stale(hours=hours)
            with self.assertRaisesRegex(ValueError, "now"):
                store.stale(hours=2, now="invalid")

    def test_parameters_are_literal_and_empty_import_does_not_cancel_games(self):
        identifier = "game'); DROP TABLE games; --"
        with ScheduleStore(self.path) as store:
            store.import_records([record(identifier=identifier)], "balldontlie")
            self.assertEqual(store.import_records([], "balldontlie"), 0)
            self.assertEqual(store.query()[0]["provider_game_id"], identifier)
            self.assertEqual(store.query(provider="' OR 1=1 --"), [])
            self.assertEqual(store.query()[0]["status"], "scheduled")

    def test_cli_import_query_and_stale_are_persistent_and_offline(self):
        fixture = Path(__file__).parent / "fixtures" / "stored_schedules.json"
        def run(*args):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([*args, "--database", str(self.path)]), 0)
            return json.loads(output.getvalue())
        with patch("sportsiq.cli.GamesClient", side_effect=AssertionError("network forbidden")):
            for _ in range(2):
                result = run("import-schedule", "--fixture", str(fixture), "--provider", "balldontlie",
                             "--retrieved-at", "2026-10-18T12:00:00Z")
                self.assertEqual(result, {"imported": 2})
            games = run("stored-schedule", "--league", "nba", "--date", "2026-10-21")
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0]["home_name"], "Example NBA Home")
            self.assertEqual(len(run("stored-schedule")), 2)
            self.assertEqual(len(run("stale-schedules", "--hours", "1", "--now", "2026-10-18T14:00:00Z")), 2)
            self.assertEqual(run("stale-schedules", "--hours", "2", "--now", "2026-10-18T14:00:00Z"), [])

    def test_cli_invalid_input_is_clear_and_does_not_import_records(self):
        fixture = Path(self.temp.name) / "invalid.json"
        for content, message in (("invalid JSON", "JSON"), ("{}", "array"),
                                 (json.dumps([dict(record(), status="bogus")]), "record 1.*status")):
            fixture.write_text(content)
            errors = StringIO()
            with self.subTest(content=content), redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                main(["import-schedule", "--fixture", str(fixture), "--provider", "balldontlie",
                      "--database", str(self.path)])
            self.assertEqual(raised.exception.code, 2)
            self.assertRegex(errors.getvalue(), message)
        with ScheduleStore(self.path) as store:
            self.assertEqual(store.query(), [])

    def test_existing_nfl_and_nba_fixture_command_output_is_importable(self):
        for league, filename, day, provider in (
            ("nfl", "nfl_scoreboard.json", "2026-09-13", "espn"),
            ("nba", "nba_games.json", "2026-10-21", "balldontlie"),
        ):
            output = StringIO()
            fixture = Path(__file__).parent / "fixtures" / filename
            with redirect_stdout(output):
                main(["schedule", "--league", league, "--date", day, "--fixture", str(fixture)])
            with ScheduleStore(self.path) as store:
                store.import_records(json.loads(output.getvalue()), provider)
                self.assertEqual(len(store.query(league=league, day=day)), 1)

    def test_all_domain_statuses_and_provider_scoping_with_in_batch_duplicates(self):
        with ScheduleStore(self.path) as store:
            records = [dict(record(), status=status.value) for status in GameStatus]
            self.assertEqual(store.import_records(records, "balldontlie"), len(GameStatus))
            self.assertEqual(len(store.query()), 1)
            self.assertEqual(len(store.history(store.query()[0]["id"])), len(GameStatus) - 1)
            other = record()
            other["provider_ids"] = {"other": "synthetic-1"}
            other["home"]["provider_ids"] = {"other": "11"}
            other["away"]["provider_ids"] = {"other": "12"}
            store.import_records([other], "other")
            self.assertEqual(len(store.query()), 2)

    def test_transaction_failure_rolls_back_history_and_material_changes(self):
        with ScheduleStore(self.path) as store:
            store.import_records([record()], "balldontlie", retrieved_at="2026-10-18T12:00:00Z")
            store.import_records([record(identifier="newer")], "balldontlie", retrieved_at="2026-10-18T15:00:00Z")
            before = store.query()
            with self.assertRaisesRegex(ValueError, "record 2.*older"):
                store.import_records([dict(record(), status="canceled"), record(identifier="newer")],
                                     "balldontlie", retrieved_at="2026-10-18T14:00:00Z")
            self.assertEqual(store.query(), before)
            self.assertEqual(store.history(before[0]["id"]), [])


if __name__ == "__main__":
    unittest.main()
