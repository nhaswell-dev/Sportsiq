"""Offline tests; all provider records in this file are synthetic."""
import unittest
import json
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit


EVENT = "KXMVECROSSCATEGORY-S20267BTSDQSEL5EKTK7Z"
MARKET = EVENT + "-WLVISUWDL"
URL = "https://kalshi.com/markets/kxmvecrosscategory/akron-vs-miami-oh/" + EVENT + "?utm_source=kalshiapp_eventdetails&marketTicker=" + MARKET


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return BytesIO(json.dumps(response).encode())


class ClientTests(unittest.TestCase):
    def test_readonly_fixed_origin_batch_and_no_credentials(self):
        from sportsiq.providers.kalshi import KalshiClient, HOST
        ticker = "KXNCAAFGAME-26OCT16AKRMOH-MOH"
        record = {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0]}
        transport = Transport({"market": {"ticker": MARKET}}, {"markets": [record], "cursor": ""})
        client = KalshiClient(transport=transport)
        self.assertEqual(client.market(MARKET)["ticker"], MARKET)
        self.assertEqual(client.markets([ticker]), [record])
        self.assertEqual(client.requests_made, 2)
        for request, timeout in transport.requests:
            self.assertTrue(request.full_url.startswith(HOST + "/markets"))
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.get_header("Authorization"))
            self.assertLessEqual(timeout, 30)
        self.assertEqual(parse_qs(urlsplit(transport.requests[1][0].full_url).query)["tickers"], [ticker])

    def test_bounded_retries_budget_and_sanitized_errors(self):
        from sportsiq.providers.kalshi import KalshiClient, KalshiError
        sleeps = []
        error = HTTPError("https://private.invalid/secret", 429, "secret", {"Retry-After": "1"}, None)
        transport = Transport(error, {"market": {"ticker": MARKET}})
        client = KalshiClient(transport=transport, sleep=sleeps.append, max_requests=2)
        self.assertEqual(client.market(MARKET)["ticker"], MARKET)
        self.assertEqual(sleeps, [1])
        with self.assertRaisesRegex(KalshiError, "budget"):
            client.market(MARKET)
        self.assertEqual(len(transport.requests), 2)
        for code in (302, 401, 404):
            transport = Transport(HTTPError("secret", code, "secret", {}, None))
            with self.assertRaises(KalshiError) as raised:
                KalshiClient(transport=transport).market(MARKET)
            self.assertNotIn("secret", str(raised.exception))
            self.assertEqual(len(transport.requests), 1)

    def test_retry_transport_failures_and_reject_invalid_responses(self):
        from sportsiq.providers.kalshi import KalshiClient, KalshiError
        transport = Transport(URLError("secret"), {"market": {"ticker": MARKET}})
        self.assertEqual(KalshiClient(transport=transport, sleep=lambda _: None).market(MARKET)["ticker"], MARKET)
        for payload in ([], {"market": {}}, {"market": {"ticker": "OTHER-MARKET"}}):
            with self.subTest(payload=payload), self.assertRaises(KalshiError):
                KalshiClient(transport=Transport(payload)).market(MARKET)
        with self.assertRaises(KalshiError):
            KalshiClient(transport=Transport({"markets": [], "cursor": "more"})).markets([MARKET])

    def test_request_inputs_and_limits_fail_before_network(self):
        from sportsiq.providers.kalshi import KalshiClient, KalshiError
        for kwargs in ({"timeout": float("nan")}, {"timeout": 31}, {"max_requests": 0},
                       {"max_retries": 3}, {"max_retries": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                KalshiClient(**kwargs)
        transport = Transport()
        client = KalshiClient(transport=transport)
        for ticker in ("../orders", "bad-lowercase", "A-B?x=1"):
            with self.assertRaises(KalshiError):
                client.market(ticker)
        self.assertEqual(transport.requests, [])

    def test_response_size_limit_and_non_json_are_sanitized(self):
        from sportsiq.providers.kalshi import KalshiClient, KalshiError, MAX_RESPONSE_BYTES
        from unittest.mock import Mock
        for body, message in ((b"x" * (MAX_RESPONSE_BYTES + 1), "size limit"),
                              (b"private invalid JSON", "JSON"),
                              (b'{"market":{"ticker":"' + MARKET.encode() + b'","value":NaN}}', "JSON")):
            transport = Mock()
            transport.open.return_value = BytesIO(body)
            with self.subTest(message=message), self.assertRaisesRegex(KalshiError, message):
                KalshiClient(transport=transport).market(MARKET)
            self.assertEqual(transport.open.call_count, 1)

    def test_retry_exhaustion_and_excessive_retry_after_are_bounded(self):
        from sportsiq.providers.kalshi import KalshiClient, KalshiError
        errors = [HTTPError("private", 503, "private", {}, None) for _ in range(3)]
        transport = Transport(*errors)
        sleeps = []
        with self.assertRaises(KalshiError):
            KalshiClient(transport=transport, sleep=sleeps.append).market(MARKET)
        self.assertEqual((len(transport.requests), sleeps), (3, [1, 2]))
        transport = Transport(HTTPError("private", 429, "private", {"Retry-After": "120"}, None))
        with self.assertRaises(KalshiError):
            KalshiClient(transport=transport, sleep=lambda _: self.fail("unexpected sleep")).market(MARKET)
        self.assertEqual(len(transport.requests), 1)

    def test_missing_duplicate_and_unexpected_batch_records_fail_closed(self):
        from sportsiq.providers.kalshi import KalshiClient, KalshiError
        for records in ([], [{"ticker": MARKET}, {"ticker": MARKET}],
                        [{"ticker": "OTHER-MARKET"}], [{"ticker": []}], [None]):
            with self.subTest(records=records), self.assertRaises(KalshiError):
                KalshiClient(transport=Transport({"markets": records})).markets([MARKET])


class URLTests(unittest.TestCase):
    def test_preserves_exact_selected_market_and_original_url(self):
        from sportsiq.providers.kalshi import parse_kalshi_url
        result = parse_kalshi_url(URL)
        self.assertEqual(result.event_ticker, EVENT)
        self.assertEqual(result.market_ticker, MARKET)
        self.assertEqual(result.original_url, URL)

    def test_missing_or_ambiguous_market_parameter_is_rejected(self):
        from sportsiq.providers.kalshi import KalshiError, parse_kalshi_url
        for url in (URL.split("?")[0], URL + "&marketTicker=" + MARKET,
                    URL.replace(MARKET, "", 1)):
            with self.subTest(url=url), self.assertRaises(KalshiError):
                parse_kalshi_url(url)

    def test_malformed_or_untrusted_links_are_rejected_without_repair(self):
        from sportsiq.providers.kalshi import KalshiError, parse_kalshi_url
        for url in (URL.replace("https:", "http:"), URL.replace("kalshi.com", "kalshi.com.evil"),
                    URL.replace("kalshi.com", "user@kalshi.com"), URL.replace("kalshi.com", "kalshi.com:443"),
                    " " + URL, URL + "\n", URL + "#fragment", URL.replace("/markets/", "/other/"),
                    URL.replace("-WLVISUWDL", "-bad"), URL.replace("marketTicker=", "marketTicker=OTHER-"),
                    URL.replace("/akron-vs-miami-oh/", "/../"), "not a link"):
            with self.subTest(url=url), self.assertRaises(KalshiError):
                parse_kalshi_url(url)
