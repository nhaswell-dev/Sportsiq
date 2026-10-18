"""Public read-only Kalshi parlay discovery; no credentials or trading methods."""

import json
import math
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sportsiq.domain.parlay import ParlayExtraction, ParlayLeg

HOST = "https://external-api.kalshi.com/trade-api/v2"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_LEGS = 100


class KalshiError(ValueError):
    """Sanitized input, provider, or transport failure."""


def _invalid_constant(value):
    raise KalshiError("nonfinite Kalshi JSON number")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise KalshiError("nonfinite Kalshi JSON number")
    return number


def decode_metadata(body: bytes):
    """Apply identical byte/JSON limits to network responses and local fixtures."""
    if len(body) > MAX_RESPONSE_BYTES:
        raise KalshiError("Kalshi response or fixture exceeds size limit")
    try:
        return json.loads(body, parse_constant=_invalid_constant, parse_float=_finite_float)
    except KalshiError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise KalshiError("malformed Kalshi JSON response") from None


@dataclass(frozen=True)
class KalshiLink:
    original_url: str
    event_ticker: str
    market_ticker: str


_TICKER = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)+", re.ASCII)


def _ticker(value: object) -> str:
    if not isinstance(value, str) or len(value) > 200 or not _TICKER.fullmatch(value):
        raise KalshiError("invalid Kalshi ticker")
    return value


def parse_kalshi_url(url: str) -> KalshiLink:
    """Accept explicit HTTPS market links, never repair or infer a selection."""
    try:
        if not isinstance(url, str) or len(url) > 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in url):
            raise ValueError()
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.netloc not in ("kalshi.com", "www.kalshi.com")
                or parts.fragment or "#" in url):
            raise ValueError()
        path = parts.path.split("/")
        if (len(path) != 5 or path[0] or path[1] != "markets"
                or not all(re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", p) for p in path[2:4])):
            raise ValueError()
        event = _ticker(path[4])
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=20)
        selected = query.get("marketTicker", [])
        if len(selected) != 1:
            raise ValueError()
        market = _ticker(selected[0])
        if not market.startswith(event + "-"):
            raise ValueError()
        return KalshiLink(url, event, market)
    except (ValueError, TypeError):
        raise KalshiError("invalid Kalshi URL: require HTTPS market link and one exact marketTicker") from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class KalshiClient:
    """GET-only fixed-origin transport, bounded across an entire extraction.

    At most six HTTP attempts by default, including retries. No pagination or
    response-supplied URL is followed. A new instance starts a new budget.
    """

    def __init__(self, *, transport=None, timeout=10, max_retries=2,
                 max_requests=6, sleep=None):
        if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
                or not math.isfinite(timeout) or not 0 < timeout <= 30
                or type(max_retries) is not int or not 0 <= max_retries <= 2
                or type(max_requests) is not int or not 1 <= max_requests <= 6):
            raise ValueError("invalid Kalshi timeout, retry count, or request budget")
        self._transport = transport if transport is not None else build_opener(_NoRedirect())
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_requests = max_requests
        self.requests_made = 0
        self.sleep = sleep if sleep is not None else time.sleep

    def _get(self, path):
        request = Request(HOST + path, method="GET", headers={"Accept": "application/json"})
        for attempt in range(self.max_retries + 1):
            if self.requests_made >= self.max_requests:
                raise KalshiError("Kalshi request budget exhausted")
            self.requests_made += 1
            delay = min(2 ** attempt, 5)
            try:
                with self._transport.open(request, timeout=self.timeout) as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                payload = decode_metadata(body)
                if not isinstance(payload, dict):
                    raise KalshiError("malformed Kalshi response")
                return payload
            except HTTPError as error:
                code = error.code
                retry_after = error.headers.get("Retry-After", "") if error.headers else ""
                error.close()
                if code != 429 and not 500 <= code <= 599:
                    raise KalshiError(f"Kalshi HTTP {code}") from None
                try:
                    delay = float(retry_after) if retry_after else delay
                except (ValueError, OverflowError):
                    delay = min(2 ** attempt, 5)
                if not math.isfinite(delay) or not 0 <= delay <= 5:
                    raise KalshiError("Kalshi retry delay exceeds limit") from None
            except (URLError, TimeoutError, OSError, HTTPException):
                pass
            except KalshiError:
                raise
            except (ValueError, UnicodeError, RecursionError):
                raise KalshiError("malformed Kalshi JSON response") from None
            if attempt == self.max_retries:
                raise KalshiError("Kalshi request failed after bounded retries") from None
            if self.requests_made >= self.max_requests:
                raise KalshiError("Kalshi request budget exhausted")
            self.sleep(delay)
        raise AssertionError("unreachable")

    def market(self, ticker):
        ticker = _ticker(ticker)
        record = self._get("/markets/" + ticker).get("market")
        if not isinstance(record, dict) or record.get("ticker") != ticker:
            raise KalshiError("missing or mismatched Kalshi market")
        return record

    def markets(self, tickers):
        if not isinstance(tickers, list) or not 1 <= len(tickers) <= MAX_LEGS:
            raise KalshiError("require 1 to 100 underlying market tickers")
        for ticker in tickers:
            _ticker(ticker)
        requested = set(tickers)
        if len(requested) != len(tickers):
            raise KalshiError("duplicate market request")
        payload = self._get("/markets?" + urlencode({"tickers": ",".join(tickers), "limit": 100}))
        records = payload.get("markets")
        if not isinstance(records, list) or payload.get("cursor") not in (None, ""):
            raise KalshiError("incomplete Kalshi market batch")
        returned = [r.get("ticker") for r in records if isinstance(r, dict)]
        if (len(returned) != len(records) or any(not isinstance(t, str) for t in returned)
                or len(returned) != len(set(returned)) or set(returned) != requested):
            raise KalshiError("missing, duplicate, or unexpected underlying markets")
        return records


# Deliberately narrow: exact known game-winner series, not substring/title guesses.
# New proposition series require explicit mapping and tests before classification.
GAME_SERIES = {"KXNFLGAME": "nfl", "KXNBAGAME": "nba",
               "KXNCAAFGAME": "ncaaf", "KXNCAABGAME": "ncaab"}


def _selected_legs(link, combo):
    if (not isinstance(combo, dict) or combo.get("ticker") != link.market_ticker
            or combo.get("event_ticker") != link.event_ticker):
        raise KalshiError("combo market identity mismatch")
    legs = combo.get("mve_selected_legs")
    if not isinstance(legs, list) or not 1 <= len(legs) <= MAX_LEGS:
        raise KalshiError("combo must contain 1 to 100 selected legs")
    seen = set()
    for leg in legs:
        if not isinstance(leg, dict):
            raise KalshiError("invalid selected leg")
        event = _ticker(leg.get("event_ticker"))
        market = _ticker(leg.get("market_ticker"))
        if not market.startswith(event + "-") or leg.get("side") not in ("yes", "no"):
            raise KalshiError("invalid selected leg identity or side")
        if market in seen:
            raise KalshiError("duplicate or conflicting selected leg")
        seen.add(market)
    return legs


def _text(record, key):
    value = record.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _timestamp(record, field, source, label, gaps):
    value = record.get(field)
    if value is None:
        return None
    try:
        if not isinstance(value, str):
            raise ValueError()
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
    except (ValueError, OverflowError):
        gaps.append(f"invalid_{label}_time")
        return None
    # Retain the original timezone/precision; raw metadata remains authoritative.
    return {"value": value, "source": source + "." + field}


def extract_parlay(link: KalshiLink, bundle: dict, *, source="offline", requests_made=0) -> ParlayExtraction:
    """Pure extraction from explicit metadata; observation is NOT pregame evidence.

    Optional milestone records are exact-event joins supplied by the caller.
    Live market discovery does not fetch milestones or infer kickoff from ticker
    dates, market close/expiration, occurrence_datetime, or milestone end_date.
    """
    if not isinstance(bundle, dict):
        raise KalshiError("invalid parlay metadata bundle")
    combo = bundle.get("combo_market")
    if not isinstance(combo, dict):
        raise KalshiError("missing combo market metadata")
    selected = _selected_legs(link, combo)
    records = bundle.get("underlying_markets")
    if not isinstance(records, list) or len(records) != len(selected):
        raise KalshiError("incomplete underlying market metadata")
    by_ticker = {}
    for record in records:
        if not isinstance(record, dict):
            raise KalshiError("invalid underlying market")
        ticker = _ticker(record.get("ticker"))
        if ticker in by_ticker:
            raise KalshiError("duplicate underlying market")
        by_ticker[ticker] = record
    if set(by_ticker) != {leg["market_ticker"] for leg in selected}:
        raise KalshiError("missing or unexpected underlying market")
    milestones = bundle.get("milestones", [])
    if not isinstance(milestones, list) or len(milestones) > MAX_LEGS:
        raise KalshiError("invalid optional milestone metadata")
    by_event = {}
    targets = {leg["event_ticker"] for leg in selected}
    for milestone in milestones:
        if not isinstance(milestone, dict):
            raise KalshiError("invalid optional milestone record")
        events = []
        for key in ("related_event_tickers", "primary_event_tickers"):
            values = milestone.get(key, [])
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                raise KalshiError("invalid milestone event identities")
            events.extend(values)
        for event in set(events) & targets:
            if event in by_event:
                raise KalshiError("ambiguous milestone event mapping")
            by_event[event] = milestone
    legs = []
    for position, selected_leg in enumerate(selected, 1):
        event, ticker = selected_leg["event_ticker"], selected_leg["market_ticker"]
        record = by_ticker[ticker]
        if record.get("event_ticker") != event:
            raise KalshiError("underlying market event mismatch")
        series = event.split("-", 1)[0]
        league = GAME_SERIES.get(series, "unsupported")
        gaps = ["pregame_availability_unverified"]
        if league == "unsupported":
            gaps.append("unsupported_league")
        # Kalshi's no_sub_title can equal yes_sub_title: keep explicit side and
        # title together rather than claiming NO selects the opposing team.
        selection = _text(record, selected_leg["side"] + "_sub_title")
        title = _text(record, "title")
        description = _text(record, "rules_primary")
        for value, gap in ((selection, "missing_selection_label"), (title, "missing_market_title"),
                           (description, "missing_market_description")):
            if value is None:
                gaps.append(gap)
        milestone = by_event.get(event)
        schedule = milestone if milestone is not None else {}
        times = {
            "scheduled_start": _timestamp(schedule, "start_date", "milestone", "scheduled_start", gaps),
            "occurrence": _timestamp(record, "occurrence_datetime", "market", "occurrence", gaps),
            "market_updated": _timestamp(record, "updated_time", "market", "market_updated", gaps),
            "schedule_updated": _timestamp(schedule, "last_updated_ts", "milestone", "schedule_updated", gaps),
            # Only an explicitly reported actual-start field qualifies; never
            # infer actual start from lifecycle, occurrence, or settlement.
            "actual_start": _timestamp(schedule, "actual_start_time", "milestone", "actual_start", gaps),
        }
        for label in ("scheduled_start", "occurrence", "market_updated", "actual_start"):
            if times[label] is None:
                gaps.append("missing_" + label + "_time")
        if times["scheduled_start"] and times["occurrence"]:
            scheduled = datetime.fromisoformat(times["scheduled_start"]["value"])
            occurrence = datetime.fromisoformat(times["occurrence"]["value"])
            if scheduled != occurrence:
                gaps.append("scheduled_occurrence_mismatch")
        legs.append(ParlayLeg(position, event, ticker, selected_leg["side"], league,
                              "event_ticker.series:" + series, selection, title, description,
                              times, gaps, deepcopy(selected_leg), deepcopy(record), deepcopy(milestone)))
    return ParlayExtraction(link.original_url, link.event_ticker, link.market_ticker,
                            source, datetime.now(timezone.utc).isoformat(), requests_made,
                            len(legs), legs, deepcopy(combo), [
                                "Discovery only; no historical pregame availability established.",
                                "Raw API metadata may contain outcomes and current prices; not prediction inputs.",
                                "NO is the negative of the market proposition, not an inferred opponent selection.",
                            ])


def fetch_parlay(link: KalshiLink, client: KalshiClient) -> ParlayExtraction:
    """One combo GET and one exact-ticker batch GET, plus bounded retries."""
    combo = client.market(link.market_ticker)
    selected = _selected_legs(link, combo)
    records = client.markets([leg["market_ticker"] for leg in selected])
    return extract_parlay(link, {"combo_market": combo, "underlying_markets": records},
                          source="live", requests_made=client.requests_made)
