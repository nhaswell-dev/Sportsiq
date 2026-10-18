"""Parse ESPN-shaped NFL scoreboard data; never perform network requests."""

from datetime import date, datetime, timezone

from sportsiq.domain.models import Game, GameStatus, League, Team
from sportsiq.providers.base import ScoreboardSource


class ESPNNFLScheduleProvider:
    def __init__(self, source: ScoreboardSource) -> None:
        self.source = source

    def games_on(self, day: date) -> list[Game]:
        payload = self.source.get_scoreboard(day)
        games: list[Game] = []
        for event in payload["events"]:
            start = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
            if start.tzinfo is None or start.utcoffset() is None:
                raise ValueError("scoreboard start time must include a timezone")
            competitors = event["competitions"][0]["competitors"]
            by_side = {entry["homeAway"]: entry["team"] for entry in competitors}
            type_info = event.get("status", {}).get("type", {})
            named_status = {
                "STATUS_SCHEDULED": GameStatus.SCHEDULED,
                "STATUS_IN_PROGRESS": GameStatus.IN_PROGRESS,
                "STATUS_FINAL": GameStatus.FINAL,
                "STATUS_POSTPONED": GameStatus.POSTPONED,
                "STATUS_CANCELED": GameStatus.CANCELED,
                "STATUS_DELAYED": GameStatus.DELAYED,
                "STATUS_SUSPENDED": GameStatus.SUSPENDED,
            }
            if type_info.get("name") is not None:
                status = named_status.get(type_info["name"], GameStatus.UNKNOWN)
            else:
                status = {"pre": GameStatus.SCHEDULED, "in": GameStatus.IN_PROGRESS,
                          "post": GameStatus.FINAL}.get(type_info.get("state"), GameStatus.UNKNOWN)
            game = Game(
                home=Team(by_side["home"]["displayName"], {"espn": str(by_side["home"]["id"])}),
                away=Team(by_side["away"]["displayName"], {"espn": str(by_side["away"]["id"])}),
                start_time=start.astimezone(timezone.utc),
                provider_ids={"espn": str(event["id"])},
                league=League.NFL,
                status=status,
            )
            if game.start_time.date() == day:
                games.append(game)
        return games
