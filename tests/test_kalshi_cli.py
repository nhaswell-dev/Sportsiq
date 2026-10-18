"""CLI integration, all network activity replaced by an injected transport."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from sportsiq.cli import main
from sportsiq.providers.kalshi import KalshiClient, KalshiError, parse_kalshi_url
from test_kalshi import URL, Transport
from test_kalshi_extraction import bundle


class ParlayCLITests(unittest.TestCase):
    def test_live_orchestration_is_two_gets_and_46_legs(self):
        from sportsiq.providers.kalshi import fetch_parlay
        data = bundle(46)
        transport = Transport({"market": data["combo_market"]}, {"markets": data["underlying_markets"], "cursor": ""})
        client = KalshiClient(transport=transport, max_retries=0, max_requests=2)
        result = asdict(fetch_parlay(parse_kalshi_url(URL), client))
        self.assertEqual((result["leg_count"], result["requests_made"], result["source"]), (46, 2, "live"))
        self.assertEqual(len(transport.requests), 2)

    def test_invalid_combo_stops_before_details(self):
        from sportsiq.providers.kalshi import fetch_parlay
        data = bundle()
        data["combo_market"]["mve_selected_legs"] *= 2
        transport = Transport({"market": data["combo_market"]})
        with self.assertRaises(KalshiError):
            fetch_parlay(parse_kalshi_url(URL), KalshiClient(transport=transport))
        self.assertEqual(len(transport.requests), 1)

    def test_offline_cli_json_and_summary_never_construct_network_or_storage(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "parlay.json"
            data = bundle(2)
            data["underlying_markets"][0]["title"] = "Synthetic\x1b[31m\nprovider title"
            path.write_text(json.dumps(data))
            for fmt in ("json", "summary"):
                out = StringIO()
                with patch("sportsiq.cli.KalshiClient") as client, patch("sportsiq.cli._project_key") as key, \
                        patch("sportsiq.cli.ScheduleStore") as store, redirect_stdout(out):
                    self.assertEqual(main(["kalshi-parlay", "--url", URL, "--offline", str(path), "--format", fmt]), 0)
                client.assert_not_called()
                key.assert_not_called()
                store.assert_not_called()
                if fmt == "json":
                    result = json.loads(out.getvalue())
                    self.assertEqual((result["leg_count"], result["requests_made"]), (2, 0))
                    self.assertEqual(result["original_url"], URL)
                else:
                    self.assertIn("2 legs", out.getvalue())
                    self.assertIn("NCAAF", out.getvalue())
                    self.assertIn("occurrence", out.getvalue())
                    self.assertNotIn("\x1b", out.getvalue())
                    self.assertIn("missing_scheduled_start_time", out.getvalue())

    def test_cli_requires_explicit_source_and_handles_fixture_errors(self):
        for args in ([], ["--live", "--offline", "ignored"], ["--offline", "/nonexistent/fixture.json"],
                     ["--offline", "ignored", "--no-retries"]):
            with self.subTest(args=args), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
                main(["kalshi-parlay", "--url", URL, *args])
            self.assertEqual(raised.exception.code, 2)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("[]")
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
                main(["kalshi-parlay", "--url", URL, "--offline", str(path)])
            self.assertEqual(raised.exception.code, 2)

    def test_live_cli_uses_bounded_client_and_reports_sanitized_failure(self):
        out = StringIO()
        data = bundle()
        transport = Transport({"market": data["combo_market"]}, {"markets": data["underlying_markets"]})
        with patch("sportsiq.cli.KalshiClient", return_value=KalshiClient(transport=transport)) as factory, redirect_stdout(out):
            self.assertEqual(main(["kalshi-parlay", "--url", URL, "--live", "--no-retries"]), 0)
        factory.assert_called_once_with(max_retries=0, max_requests=2)
        self.assertEqual(json.loads(out.getvalue())["leg_count"], 1)

    def test_committed_synthetic_fixture_is_exercised_by_cli(self):
        fixture = Path(__file__).parent / "fixtures" / "kalshi_parlay.json"
        url = "https://kalshi.com/markets/kxmvecrosscategory/synthetic/KXMVECROSSCATEGORY-SYNTHETIC?marketTicker=KXMVECROSSCATEGORY-SYNTHETIC-EXAMPLE"
        out = StringIO()
        with redirect_stdout(out):
            main(["kalshi-parlay", "--url", url, "--offline", str(fixture)])
        result = json.loads(out.getvalue())
        self.assertEqual([l["side"] for l in result["legs"]], ["yes", "no"])
        self.assertEqual([l["league"] for l in result["legs"]], ["nfl", "ncaaf"])
        self.assertEqual(result["requests_made"], 0)

    def test_offline_invalid_json_and_oversize_are_sanitized(self):
        from sportsiq.providers.kalshi import MAX_RESPONSE_BYTES
        with TemporaryDirectory() as directory:
            fixture = Path(directory) / "bad.json"
            for body in (b"private invalid JSON", b"x" * (MAX_RESPONSE_BYTES + 1), b'{"private":NaN}'):
                fixture.write_bytes(body)
                error = StringIO()
                with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                    main(["kalshi-parlay", "--url", URL, "--offline", str(fixture)])
                self.assertEqual(raised.exception.code, 2)
                self.assertNotIn("private", error.getvalue())
