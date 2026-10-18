"""Normalize synthetic BALLDONTLIE-shaped NBA fixtures without HTTP access."""

from datetime import date, datetime, timezone

from sportsiq.domain.models import Game, GameStatus, League, Team
from sportsiq.providers.base import ScheduleSource


class NBAFixtureScheduleProvider:
    def __init__(self, source: ScheduleSource) -> None:
        self.source = source

    def games_on(self, day: date) -> list[Game]:
        payload = self.source.get_schedule(day)
        games: list[Game] = []
        for record in payload["data"]:
            timestamp = record.get("datetime")
            if not timestamp:
                raise ValueError("NBA fixture tipoff datetime is required")
            start = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if start.tzinfo is None or start.utcoffset() is None:
                raise ValueError("NBA fixture start time must include a timezone")
            home = record["home_team"]
            away = record["visitor_team"]
            try:
                status = GameStatus(record.get("status_state"))
            except ValueError:
                status = GameStatus.UNKNOWN
            game = Game(
                home=Team(home["full_name"], {"balldontlie": str(home["id"])}, home.get("abbreviation")),
                away=Team(away["full_name"], {"balldontlie": str(away["id"])}, away.get("abbreviation")),
                start_time=start.astimezone(timezone.utc),
                provider_ids={"balldontlie": str(record["id"])},
                league=League.NBA,
                status=status,
            )
            if game.start_time.date() == day:
                games.append(game)
        return games
