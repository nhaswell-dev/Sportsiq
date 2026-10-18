"""Schedule provider and scoreboard source contracts."""

from datetime import date
from typing import Any, Mapping, Protocol

from sportsiq.domain.models import Game


class ScheduleProvider(Protocol):
    def games_on(self, day: date) -> list[Game]: ...


class ScoreboardSource(Protocol):
    def get_scoreboard(self, day: date) -> Mapping[str, Any]: ...
