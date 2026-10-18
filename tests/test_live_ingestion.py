import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from email.message import Message
from io import StringIO
from http.client import IncompleteRead
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from sportsiq.cli import main
from sportsiq.providers.balldontlie import GamesClient
from sportsiq.storage.schedule import ScheduleStore
from test_balldontlie import Transport, game


class LiveIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "data" / "schedule.sqlite3"

    def run_import(self, transport, league="nfl", *options):
        output = StringIO()
        def client(key, **kwargs):
            return GamesClient(key, transport=transport, clock=lambda: 0,
                               sleep=lambda seconds: None, **kwargs)
        with patch("sportsiq.cli._project_key", return_value="test-key"), \
                patch("sportsiq.cli.GamesClient", side_effect=client), redirect_stdout(output):
            code = main(["import-live-schedule", "--league", league, "--date", "2026-10-21",
                         "--database", str(self.path), *options])
        return code, json.loads(output.getvalue())

    def test_imports_both_leagues_with_validated_fields_and_retrieval_time(self):
        for league in ("nfl", "nba"):
            code, result = self.run_import(Transport({"data": [game(league)], "meta": {}}), league)
            self.assertEqual(code, 0)
            self.assertEqual(result["imported"], 1)
            with ScheduleStore(self.path) as store:
                row = store.query(league=league)[0]
            self.assertEqual(row["provider_game_id"], "77")
            self.assertEqual(row["home_id"], "11")
            self.assertEqual(row["away_name"], "Away")
            self.assertEqual(row["status"], "scheduled")
            self.assertEqual(row["start_time"], "2026-10-21T03:30:00.000000+00:00")
            self.assertIsNotNone(datetime.fromisoformat(row["retrieved_at"]).utcoffset())
            self.assertEqual(row["retrieved_at"], result["retrieved_at"])

    def test_dry_run_validates_without_creating_or_touching_database(self):
        before = b""
        for existing in (False, True):
            if existing:
                self.run_import(Transport({"data": [game()], "meta": {}}))
                before = self.path.read_bytes()
            _, result = self.run_import(Transport({"data": [game()], "meta": {}}), "nfl", "--dry-run")
            self.assertEqual(result["validated"], 1)
            self.assertEqual(result["imported"], 0)
            self.assertTrue(result["complete"])
            if existing:
                self.assertEqual(self.path.read_bytes(), before)
            else:
                self.assertFalse(self.path.parent.exists())

    def test_utc_boundaries_report_exclusions_without_rewriting_source_instants(self):
        for league in ("nfl", "nba"):
            records = [game(league, "2026-10-20T20:00:00-04:00"),
                       dict(game(league, "2026-10-21T23:59:59Z"), id=78),
                       dict(game(league, "2026-10-20T23:59:59Z"), id=79),
                       dict(game(league, "2026-10-22T00:00:00Z"), id=80)]
            _, result = self.run_import(Transport({"data": records, "meta": {}}), league)
            self.assertEqual(result["validated"], 2)
            self.assertEqual([r["provider_game_id"] for r in result["excluded"]], ["79", "80"])
            self.assertEqual(result["excluded"][1]["source_timestamp"], "2026-10-22T00:00:00Z")
            with ScheduleStore(self.path) as store:
                self.assertEqual(store.query(league=league)[0]["start_time"],
                                 "2026-10-21T00:00:00.000000+00:00")

    def test_single_request_dry_run_reports_partial_pagination(self):
        transport = Transport({"data": [game()], "meta": {"next_cursor": 78}})
        code, result = self.run_import(transport, "nfl", "--dry-run", "--single-request")
        self.assertEqual(code, 0)
        self.assertFalse(result["complete"])
        self.assertEqual(result["pages"], 1)
        self.assertEqual(result["validated"], 1)
        self.assertEqual(len(transport.requests), 1)
        self.assertFalse(self.path.exists())

    def assert_failed_import(self, transport, *options):
        errors = StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            self.run_import(transport, "nfl", *options)
        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn("test-key", errors.getvalue())
        return errors.getvalue()

    def test_incomplete_envelopes_never_create_database(self):
        for payload in ({"data": []}, {"data": [], "meta": None},
                        {"data": [game()] * 100, "meta": {}},
                        {"data": [game()] * 25, "meta": {"per_page": 25}},
                        {"data": [], "meta": {"next_cursor": True}}):
            with self.subTest(payload_type=type(payload.get("meta")).__name__):
                self.assert_failed_import(Transport(payload))
                self.assertFalse(self.path.exists())

    def test_transport_failures_are_sanitized_and_leave_database_untouched(self):
        failures = [TimeoutError("test-key"), URLError("test-key"),
                    IncompleteRead(b"test-key", 100),
                    HTTPError("test-key", 401, "test-key", Message(), None),
                    HTTPError("test-key", 429, "test-key", Message(), None),
                    HTTPError("test-key", 503, "test-key", Message(), None)]
        for error in failures:
            with self.subTest(error=type(error).__name__):
                transport = Transport(error)
                self.assert_failed_import(transport, "--dry-run", "--single-request")
                self.assertEqual(len(transport.requests), 1)
                self.assertFalse(self.path.exists())

    def test_duplicate_records_across_pages_are_imported_once(self):
        transport = Transport({"data": [game()], "meta": {"next_cursor": 78}},
                              {"data": [game()], "meta": {"next_cursor": None}})
        _, result = self.run_import(transport)
        self.assertEqual(result["imported"], 1)
        with ScheduleStore(self.path) as store:
            self.assertEqual(len(store.query()), 1)

    def test_repeated_imports_and_changes_use_existing_history_for_both_leagues(self):
        for league in ("nfl", "nba"):
            for _ in range(2):
                self.run_import(Transport({"data": [game(league)], "meta": {}}), league)
            with ScheduleStore(self.path) as store:
                before = store.query(league=league)[0]
                self.assertEqual(store.history(before["id"]), [])
            self.run_import(Transport({"data": [game(league, "2026-10-21T05:00:00Z", "postponed")],
                                       "meta": {}}), league)
            with ScheduleStore(self.path) as store:
                rows = store.query(league=league)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["id"], before["id"])
                self.assertEqual(rows[0]["created_at"], before["created_at"])
                self.assertEqual(rows[0]["status"], "postponed")
                changes = store.history(before["id"])
                self.assertEqual(len(changes), 1)
                self.assertEqual(changes[0]["before"]["start_time"], before["start_time"])

    def test_later_page_failure_never_persists_first_page(self):
        self.run_import(Transport({"data": [game()], "meta": {}}))
        before = self.path.read_bytes()
        transport = Transport({"data": [game(status="final")], "meta": {"next_cursor": 78}},
                              TimeoutError("test-key"))
        self.assert_failed_import(transport)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_records_including_outside_day_fail_before_database_access(self):
        for record in (dict(game(), home_team={"id": 11, "full_name": " "}),
                       dict(game(), visitor_team=game()["home_team"]),
                       dict(game(), date=None), game(timestamp="2026-10-21T01:00:00"),
                       game(timestamp="2026-10-20T01:00:00")):
            for options in ((), ("--dry-run",)):
                with self.subTest(options=options):
                    self.assert_failed_import(Transport({"data": [game(), record], "meta": {}}), *options)
                    self.assertFalse(self.path.exists())

    def test_database_failure_rolls_back_upserts_and_history(self):
        for league in ("nfl", "nba"):
            self.run_import(Transport({"data": [game(league)], "meta": {}}), league)
        with ScheduleStore(self.path) as store:
            before = store.query()
            store.connection.execute("""CREATE TRIGGER fail_new_game BEFORE INSERT ON games
                WHEN NEW.provider_game_id = '78'
                BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
            store.connection.commit()
        for league in ("nfl", "nba"):
            transport = Transport({"data": [game(league, status="final"), dict(game(league), id=78)], "meta": {}})
            errors = StringIO()
            with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                self.run_import(transport, league)
            self.assertEqual(raised.exception.code, 2)
            with ScheduleStore(self.path) as store:
                self.assertEqual(store.query(), before)
                for row in before:
                    self.assertEqual(store.history(row["id"]), [])

    def test_single_request_without_dry_run_rejects_before_key_or_network(self):
        with patch("sportsiq.cli._project_key", side_effect=AssertionError("must not load key")):
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
                main(["import-live-schedule", "--league", "nfl", "--date", "2026-10-21", "--single-request"])
        self.assertEqual(raised.exception.code, 2)

    def test_missing_key_is_sanitized_and_never_opens_database(self):
        with patch("sportsiq.cli.PROJECT_ENV", Path(self.temp.name) / "missing.env"):
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
                main(["import-live-schedule", "--league", "nba", "--date", "2026-10-21",
                      "--database", str(self.path)])
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(self.path.exists())

    def test_empty_complete_response_never_cancels_existing_games(self):
        self.run_import(Transport({"data": [game()], "meta": {}}))
        _, result = self.run_import(Transport({"data": [], "meta": {"next_cursor": None}}))
        self.assertTrue(result["complete"])
        self.assertEqual(result["imported"], 0)
        with ScheduleStore(self.path) as store:
            self.assertEqual(store.query()[0]["status"], "scheduled")


if __name__ == "__main__":
    unittest.main()
