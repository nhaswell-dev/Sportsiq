"""Normalized, provider-independent schedule records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True)
class Team:
    name: str
    provider_ids: Mapping[str, str]


@dataclass(frozen=True)
class Game:
    home: Team
    away: Team
    start_time: datetime
    provider_ids: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.start_time.tzinfo is None or self.start_time.utcoffset() is None:
            raise ValueError("start_time must be timezone-aware")
