"""Offline-only SportsIQ command line interface."""

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Sequence

from sportsiq.domain.models import League
from sportsiq.providers.base import ScheduleProvider
from sportsiq.providers.espn_nfl import ESPNNFLScheduleProvider
from sportsiq.providers.fixture import FixtureScheduleSource, FixtureScoreboardSource
from sportsiq.providers.nba_schedule import NBAFixtureScheduleProvider


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sportsiq")
    subcommands = parser.add_subparsers(dest="command", required=True)
    schedule = subcommands.add_parser("schedule", help="Query an offline NFL or NBA fixture")
    schedule.add_argument("--league", choices=[league.value for league in League], default="nfl")
    schedule.add_argument("--date", required=True, type=date.fromisoformat, help="UTC date (YYYY-MM-DD)")
    schedule.add_argument("--fixture", required=True, type=Path, help="Local schedule-shaped JSON file")
    args = parser.parse_args(argv)

    provider: ScheduleProvider
    if args.league == League.NFL.value:
        provider = ESPNNFLScheduleProvider(FixtureScoreboardSource(args.fixture))
    else:
        provider = NBAFixtureScheduleProvider(FixtureScheduleSource(args.fixture))
    games = provider.games_on(args.date)
    records = [{**asdict(game), "start_time": game.start_time.isoformat()} for game in games]
    print(json.dumps(records, indent=2))
    return 0
