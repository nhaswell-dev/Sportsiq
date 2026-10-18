"""Local JSON source; it never connects to ESPN or another service."""

import json
from datetime import date
from pathlib import Path
from typing import Any


class FixtureScoreboardSource:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get_scoreboard(self, day: date) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))


class FixtureScheduleSource(FixtureScoreboardSource):
    """Read a local schedule-shaped JSON fixture with no network access."""

    def get_schedule(self, day: date) -> dict[str, Any]:
        return self.get_scoreboard(day)
