"""Read-only, rate-limited BALLDONTLIE NFL/NBA Games adapters."""

import json
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sportsiq.domain.models import Game, GameStatus, League, Team

HOST = "https://api.balldontlie.io"
PATHS = {League.NFL: "/nfl/v1/games", League.NBA: "/nba/v1/games"}
MIN_INTERVAL = 12.1  # Five requests per minute, shared across clients in this process.
_last_request: float | None = None
_rate_lock = threading.Lock()


class ProviderError(Exception):
    """A deliberately sanitized provider or transport failure."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward Authorization to another host.


class GamesClient:
    def __init__(self, api_key: str, *, transport=None, timeout: float = 10,
                 max_retries: int = 2, clock=None, sleep=None) -> None:
        if not api_key or not api_key.strip():
            raise ProviderError("BALLDONTLIE_API_KEY is missing")
        if timeout <= 0 or not 0 <= max_retries <= 2:
            raise ValueError("invalid timeout or retry count")
        self._key = api_key
        self._transport = transport if transport is not None else build_opener(_NoRedirect())
        self.timeout = timeout
        self.max_retries = max_retries
        self.clock = clock if clock is not None else time.monotonic
        self.sleep = sleep if sleep is not None else time.sleep
        self._last_request: float | None = None

    def _throttle(self) -> None:
        global _last_request
        with _rate_lock:
            # Injected test clocks are isolated; real clients share the process quota.
            last = self._last_request if self.clock is not time.monotonic else _last_request
            now = self.clock()
            if last is not None and now - last < MIN_INTERVAL:
                self.sleep(MIN_INTERVAL - (now - last))
            if self.clock is time.monotonic:
                _last_request = self.clock()
            else:
                self._last_request = self.clock()

    def page(self, league: League, days: list[date], cursor: int | None = None) -> dict[str, Any]:
        if league not in PATHS:
            raise ValueError("unsupported league")
        params: list[tuple[str, str]] = [("dates[]", day.isoformat()) for day in days]
        params.append(("per_page", "100"))
        if cursor is not None:
            params.append(("cursor", str(cursor)))
        # Host and path are constants; neither a response nor a caller can supply a URL.
        request = Request(HOST + PATHS[league] + "?" + urlencode(params),
                          headers={"Authorization": self._key, "Accept": "application/json"})
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                with self._transport.open(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise ProviderError("Malformed BALLDONTLIE games response")
                meta = payload.get("meta")
                if not isinstance(meta, dict):
                    raise ProviderError("Malformed BALLDONTLIE pagination metadata")
                per_page = meta.get("per_page", 100)
                if not isinstance(per_page, int) or isinstance(per_page, bool) or not 1 <= per_page <= 100:
                    raise ProviderError("Malformed BALLDONTLIE page size")
                if len(payload["data"]) >= per_page and "next_cursor" not in meta:
                    raise ProviderError("Incomplete BALLDONTLIE pagination metadata")
                return payload
            except HTTPError as error:
                if error.code in (401, 403):
                    raise ProviderError("BALLDONTLIE authentication or entitlement failed") from None
                if error.code != 429 and not 500 <= error.code <= 599:
                    raise ProviderError(f"BALLDONTLIE HTTP {error.code}") from None
                if attempt == self.max_retries:
                    raise ProviderError(f"BALLDONTLIE HTTP {error.code} after retries") from None
                retry_after = error.headers.get("Retry-After", "") if error.headers else ""
                try:
                    delay = max(MIN_INTERVAL, float(retry_after))
                except (ValueError, OverflowError):
                    delay = MIN_INTERVAL
                if not 0 < delay <= 60:
                    raise ProviderError("BALLDONTLIE rate limit retry delay exceeds 60 seconds") from None
                self.sleep(delay)
            except (URLError, TimeoutError, OSError, HTTPException, json.JSONDecodeError, UnicodeError):
                raise ProviderError("BALLDONTLIE transport or JSON response failed") from None
        raise AssertionError("unreachable")


@dataclass
class ScheduleCollection:
    games: list[Game]
    excluded: list[dict[str, str]]
    pages: int
    complete: bool


class BALLDONTLIEGamesProvider:
    def __init__(self, league: League, client: GamesClient) -> None:
        if league not in PATHS:
            raise ValueError("unsupported league")
        self.league = league
        self.client = client

    def games_on(self, day: date) -> list[Game]:
        return self.collect_on(day).games

    def collect_on(self, day: date, *, max_pages: int | None = None) -> ScheduleCollection:
        # The provider filters by game date, while the domain query is UTC day.
        # Include neighboring provider dates to account for timezone rollover.
        days = [day - timedelta(days=1), day, day + timedelta(days=1)]
        games: list[Game] = []
        excluded: list[dict[str, str]] = []
        pages = 0
        seen_cursors: set[int] = set()
        seen_games: set[str] = set()
        cursor = None
        while True:
            payload = self.client.page(self.league, days, cursor)
            pages += 1
            for record in payload["data"]:
                game = self._normalize(record)
                identifier = game.provider_ids["balldontlie"]
                if game.start_time.date() == day and identifier not in seen_games:
                    seen_games.add(identifier)
                    games.append(game)
                elif game.start_time.date() != day:
                    excluded.append({"provider_game_id": identifier,
                                     "source_timestamp": record["date" if self.league == League.NFL else "datetime"],
                                     "start_time": game.start_time.isoformat(),
                                     "reason": "outside requested UTC date"})
            cursor = payload.get("meta", {}).get("next_cursor")
            if cursor is None:
                return ScheduleCollection(games, excluded, pages, True)
            if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0 or cursor in seen_cursors:
                raise ProviderError("Malformed BALLDONTLIE pagination cursor")
            seen_cursors.add(cursor)
            if max_pages is not None and pages >= max_pages:
                return ScheduleCollection(games, excluded, pages, False)

    def _normalize(self, record: Any) -> Game:
        try:
            if not isinstance(record, dict):
                raise ValueError()
            timestamp = record["date"] if self.league == League.NFL else record["datetime"]
            if not isinstance(timestamp, str) or not timestamp:
                raise ValueError()
            start = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if start.tzinfo is None or start.utcoffset() is None:
                raise ValueError()
            def team(value):
                if (not isinstance(value, dict) or not isinstance(value.get("full_name"), str)
                        or not value["full_name"].strip()
                        or not isinstance(value.get("id"), int) or isinstance(value.get("id"), bool)):
                    raise ValueError()
                abbreviation = value.get("abbreviation")
                if abbreviation is not None and (not isinstance(abbreviation, str) or not abbreviation.strip()):
                    raise ValueError()
                return Team(value["full_name"], {"balldontlie": str(value["id"])},
                            value.get("abbreviation"))
            status_value = record.get("status_state", "unknown")
            try:
                status = GameStatus(status_value)
            except ValueError:
                status = GameStatus.UNKNOWN
            if not isinstance(record.get("id"), int) or isinstance(record.get("id"), bool):
                raise ValueError()
            home, away = team(record["home_team"]), team(record["visitor_team"])
            if home.provider_ids == away.provider_ids:
                raise ValueError()
            return Game(home=home, away=away,
                        start_time=start.astimezone(timezone.utc),
                        provider_ids={"balldontlie": str(record["id"])},
                        league=self.league, status=status)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ProviderError("Malformed BALLDONTLIE game record") from None
