"""Normalized, provider-independent schedule records."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping


class League(str, Enum):
    NFL = "nfl"
    NBA = "nba"


class GameStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELED = "canceled"
    DELAYED = "delayed"
    SUSPENDED = "suspended"
    ABANDONED = "abandoned"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Team:
    name: str
    provider_ids: Mapping[str, str]
    abbreviation: str | None = None


@dataclass(frozen=True)
class Game:
    home: Team
    away: Team
    start_time: datetime
    provider_ids: Mapping[str, str]
    # NFL default preserves the original four-positional-argument constructor.
    league: League = League.NFL
    status: GameStatus = GameStatus.UNKNOWN

    def __post_init__(self) -> None:
        if self.start_time.tzinfo is None or self.start_time.utcoffset() is None:
            raise ValueError("start_time must be timezone-aware")
