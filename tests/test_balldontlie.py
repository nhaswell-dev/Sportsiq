import json
import unittest
from contextlib import redirect_stdout
from datetime import date, timezone
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from sportsiq.cli import main
from sportsiq.domain.models import GameStatus, League
from sportsiq.providers.balldontlie import BALLDONTLIEGamesProvider, GamesClient, ProviderError


class Response:
    def __init__(self, payload):
        self.body = BytesIO(json.dumps(payload).encode())
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.body.close()

    def read(self, size=-1):
        return self.body.read(size)


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return Response(response)


def game(league="nfl", timestamp="2026-10-21T03:30:00Z", status="scheduled"):
    return {"id": 77, "date": timestamp if league == "nfl" else "2026-10-20",
            "datetime": timestamp, "status_state": status,
            "home_team": {"id": 11, "full_name": "Home", "abbreviation": "HOM"},
            "visitor_team": {"id": 12, "full_name": "Away", "abbreviation": "AWY"}}


def provider(league, transport, **kwargs):
    return BALLDONTLIEGamesProvider(league, GamesClient("test-key", transport=transport,
                                 clock=lambda: 0, sleep=lambda seconds: None, **kwargs))


class BALLDONTLIETests(unittest.TestCase):
    def test_nfl_normalizes_and_filters_utc_day(self):
        transport = Transport({"data": [game(), game(timestamp="2026-10-20T17:00:00Z")], "meta": {}})
        result = provider(League.NFL, transport).games_on(date(2026, 10, 21))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].provider_ids, {"balldontlie": "77"})
        self.assertEqual(result[0].home.provider_ids, {"balldontlie": "11"})
        self.assertEqual(result[0].away.abbreviation, "AWY")
        self.assertEqual(result[0].start_time.isoformat(), "2026-10-21T03:30:00+00:00")
        self.assertEqual(result[0].start_time.tzinfo, timezone.utc)
        self.assertEqual(result[0].status, GameStatus.SCHEDULED)
        request, timeout = transport.requests[0]
        self.assertEqual(urlsplit(request.full_url).netloc, "api.balldontlie.io")
        self.assertEqual(urlsplit(request.full_url).path, "/nfl/v1/games")
        self.assertEqual(parse_qs(urlsplit(request.full_url).query)["dates[]"],
                         ["2026-10-20", "2026-10-21", "2026-10-22"])
        self.assertEqual(request.get_header("Authorization"), "test-key")
        self.assertGreater(timeout, 0)

    def test_nba_uses_documented_endpoint_and_datetime(self):
        transport = Transport({"data": [game("nba", "2026-10-20T23:30:00-04:00", "final")], "meta": {}})
        result = provider(League.NBA, transport).games_on(date(2026, 10, 21))
        self.assertEqual(result[0].league, League.NBA)
        self.assertEqual(result[0].status, GameStatus.FINAL)
        self.assertEqual(result[0].start_time.isoformat(), "2026-10-21T03:30:00+00:00")
        self.assertEqual(urlsplit(transport.requests[0][0].full_url).path, "/nba/v1/games")

    def test_pagination_preserves_filter_and_rate_spaces_calls(self):
        responses = ({"data": [game()], "meta": {"next_cursor": 78}},
                     {"data": [dict(game(), id=78)], "meta": {"next_cursor": None}})
        transport = Transport(*responses)
        now = [0.0]
        sleeps = []
        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds
        client = GamesClient("test-key", transport=transport, clock=lambda: now[0], sleep=sleep)
        result = BALLDONTLIEGamesProvider(League.NFL, client).games_on(date(2026, 10, 21))
        self.assertEqual([g.provider_ids["balldontlie"] for g in result], ["77", "78"])
        self.assertEqual(parse_qs(urlsplit(transport.requests[1][0].full_url).query)["cursor"], ["78"])
        self.assertEqual(len(sleeps), 1)
        self.assertGreaterEqual(sleeps[0], 12)

    def test_empty_schedule(self):
        self.assertEqual(provider(League.NBA, Transport({"data": [], "meta": {}})).games_on(date(2026, 10, 21)), [])

    def test_malformed_envelope_and_game_are_sanitized(self):
        for payload in ({"data": {}}, {"data": [game(timestamp=None)], "meta": {}},
                        {"data": [dict(game(), home_team=None)], "meta": {}}):
            with self.subTest(payload=type(payload["data"]).__name__):
                with self.assertRaises(ProviderError) as error:
                    provider(League.NFL, Transport(payload)).games_on(date(2026, 10, 21))
                self.assertNotIn("test-key", str(error.exception))

    def test_authentication_error_never_retries_or_echoes_response(self):
        error = HTTPError("https://api.balldontlie.io/nfl/v1/games?secret=test-key", 401,
                          "test-key", {}, BytesIO(b"test-key"))
        transport = Transport(error)
        with self.assertRaisesRegex(ProviderError, "authentication") as raised:
            provider(League.NFL, transport).games_on(date(2026, 10, 21))
        self.assertEqual(len(transport.requests), 1)
        self.assertNotIn("test-key", str(raised.exception))

    def test_rate_limit_retries_bounded_with_backoff(self):
        errors = [HTTPError("secret", 429, "secret", {"Retry-After": "13"}, None) for _ in range(3)]
        transport = Transport(*errors)
        sleeps = []
        now = [0.0]
        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds
        client = GamesClient("test-key", transport=transport, clock=lambda: now[0], sleep=sleep, max_retries=2)
        with self.assertRaisesRegex(ProviderError, "429"):
            BALLDONTLIEGamesProvider(League.NBA, client).games_on(date(2026, 10, 21))
        self.assertEqual(len(transport.requests), 3)
        self.assertTrue(all(seconds >= 13 for seconds in sleeps))

    def test_server_errors_retry_but_network_exception_is_sanitized(self):
        transport = Transport(HTTPError("secret", 503, "secret", {}, None), {"data": [], "meta": {}})
        self.assertEqual(provider(League.NBA, transport).games_on(date(2026, 10, 21)), [])
        self.assertEqual(len(transport.requests), 2)
        with self.assertRaises(ProviderError) as raised:
            provider(League.NBA, Transport(URLError("test-key"))).games_on(date(2026, 10, 21))
        self.assertNotIn("test-key", str(raised.exception))

    def test_repeated_cursor_is_rejected(self):
        transport = Transport(*[{"data": [], "meta": {"next_cursor": 77}} for _ in range(2)])
        with self.assertRaisesRegex(ProviderError, "cursor"):
            provider(League.NFL, transport).games_on(date(2026, 10, 21))

    def test_cli_defaults_to_fixture_and_live_loads_project_env(self):
        fixture = Path(__file__).parent / "fixtures" / "nba_games.json"
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["schedule", "--league", "nba", "--date", "2026-10-21", "--fixture", str(fixture)]), 0)
        self.assertEqual(len(json.loads(output.getvalue())), 1)
        with TemporaryDirectory() as temp:
            env_path = Path(temp) / ".env"
            env_path.write_text('BALLDONTLIE_API_KEY="test-key"\n')
            with patch("sportsiq.cli.PROJECT_ENV", env_path), patch("sportsiq.cli.GamesClient") as client:
                with patch("sportsiq.cli.BALLDONTLIEGamesProvider") as live:
                    live.return_value.games_on.return_value = []
                    with redirect_stdout(StringIO()):
                        main(["schedule", "--provider", "balldontlie", "--league", "nfl", "--date", "2026-10-21"])
                    client.assert_called_once_with("test-key")
                    live.assert_called_once()

    def test_missing_key_is_sanitized(self):
        with TemporaryDirectory() as temp:
            with patch("sportsiq.cli.PROJECT_ENV", Path(temp) / ".env"):
                with self.assertRaisesRegex(ProviderError, "BALLDONTLIE_API_KEY"):
                    main(["schedule", "--provider", "balldontlie", "--date", "2026-10-21"])


if __name__ == "__main__":
    unittest.main()
