"""Offline-by-default SportsIQ schedule command line interface."""

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Sequence

from sportsiq.domain.models import League
from sportsiq.providers.balldontlie import BALLDONTLIEGamesProvider, GamesClient, ProviderError
from sportsiq.providers.base import ScheduleProvider
from sportsiq.providers.espn_nfl import ESPNNFLScheduleProvider
from sportsiq.providers.fixture import FixtureScheduleSource, FixtureScoreboardSource
from sportsiq.providers.nba_schedule import NBAFixtureScheduleProvider

PROJECT_ENV = Path(__file__).resolve().parent.parent / ".env"


def _project_key() -> str:
    try:
        for line in PROJECT_ENV.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "BALLDONTLIE_API_KEY":
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if value:
                    return value
    except (OSError, UnicodeError):
        pass
    raise ProviderError("BALLDONTLIE_API_KEY is missing from project .env") from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sportsiq")
    subcommands = parser.add_subparsers(dest="command", required=True)
    schedule = subcommands.add_parser("schedule", help="Query an NFL or NBA schedule")
    schedule.add_argument("--league", choices=[league.value for league in League], default="nfl")
    schedule.add_argument("--date", required=True, type=date.fromisoformat, help="UTC date (YYYY-MM-DD)")
    schedule.add_argument("--provider", choices=("fixture", "balldontlie"), default="fixture")
    schedule.add_argument("--fixture", type=Path, help="Local schedule-shaped JSON file")
    args = parser.parse_args(argv)

    provider: ScheduleProvider
    if args.provider == "balldontlie":
        if args.fixture is not None:
            parser.error("--fixture cannot be used with --provider balldontlie")
        provider = BALLDONTLIEGamesProvider(League(args.league), GamesClient(_project_key()))
    elif args.fixture is None:
        parser.error("--fixture is required for the default fixture provider")
    elif args.league == League.NFL.value:
        provider = ESPNNFLScheduleProvider(FixtureScoreboardSource(args.fixture))
    else:
        provider = NBAFixtureScheduleProvider(FixtureScheduleSource(args.fixture))
    games = provider.games_on(args.date)
    records = [{**asdict(game), "start_time": game.start_time.isoformat()} for game in games]
    print(json.dumps(records, indent=2))
    return 0
