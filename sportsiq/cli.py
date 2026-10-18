"""Offline-only SportsIQ command line interface."""

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Sequence

from sportsiq.providers.espn_nfl import ESPNNFLScheduleProvider
from sportsiq.providers.fixture import FixtureScoreboardSource


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sportsiq")
    subcommands = parser.add_subparsers(dest="command", required=True)
    schedule = subcommands.add_parser("schedule", help="Query an offline NFL scoreboard fixture")
    schedule.add_argument("--date", required=True, type=date.fromisoformat, help="UTC date (YYYY-MM-DD)")
    schedule.add_argument("--fixture", required=True, type=Path, help="Local ESPN-shaped JSON file")
    args = parser.parse_args(argv)

    games = ESPNNFLScheduleProvider(FixtureScoreboardSource(args.fixture)).games_on(args.date)
    records = [{**asdict(game), "start_time": game.start_time.isoformat()} for game in games]
    print(json.dumps(records, indent=2))
    return 0
