"""Offline-by-default SportsIQ schedule command line interface."""

import argparse
import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence

from sportsiq.domain.models import League
from sportsiq.providers.balldontlie import BALLDONTLIEGamesProvider, GamesClient, ProviderError
from sportsiq.providers.base import ScheduleProvider
from sportsiq.providers.espn_nfl import ESPNNFLScheduleProvider
from sportsiq.providers.fixture import FixtureScheduleSource, FixtureScoreboardSource
from sportsiq.providers.nba_schedule import NBAFixtureScheduleProvider
from sportsiq.providers.kalshi import (
    KalshiClient, KalshiError, MAX_RESPONSE_BYTES, decode_metadata, extract_parlay, fetch_parlay, parse_kalshi_url,
)
from sportsiq.reports.parlay import parlay_summary
from sportsiq.parlay_report import add_arguments as parlay_report_arguments, run as run_parlay_report
from sportsiq.storage.schedule import DEFAULT_DATABASE, ScheduleStore, validate_record

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
    consolidated = subcommands.add_parser("parlay-report", help="Consolidated read-only parlay evidence report")
    parlay_report_arguments(consolidated)
    parlay = subcommands.add_parser("kalshi-parlay", help="Read-only Kalshi combo discovery (no predictions)")
    parlay.add_argument("--url", required=True, help="Exact Kalshi URL including marketTicker")
    parlay_source = parlay.add_mutually_exclusive_group(required=True)
    parlay_source.add_argument("--offline", type=Path, metavar="FIXTURE", help="Local metadata bundle; no network")
    parlay_source.add_argument("--live", action="store_true", help="Explicit public market-data GETs")
    parlay.add_argument("--format", choices=("json", "summary"), default="json")
    parlay.add_argument("--no-retries", action="store_true", help="Live only: at most two HTTP attempts total")
    schedule = subcommands.add_parser("schedule", help="Query an NFL or NBA schedule")
    schedule.add_argument("--league", choices=[league.value for league in League], default="nfl")
    schedule.add_argument("--date", required=True, type=date.fromisoformat, help="UTC date (YYYY-MM-DD)")
    schedule.add_argument("--provider", choices=("fixture", "balldontlie"), default="fixture")
    schedule.add_argument("--fixture", type=Path, help="Local schedule-shaped JSON file")
    importer = subcommands.add_parser("import-schedule", help="Import normalized local JSON (no API calls)")
    importer.add_argument("--fixture", type=Path, required=True)
    importer.add_argument("--provider", required=True, help="Provider namespace in fixture provider_ids")
    importer.add_argument("--retrieved-at", help="Actual observation time; defaults to import time")
    live = subcommands.add_parser("import-live-schedule", help="Explicit BALLDONTLIE schedule ingestion")
    live.add_argument("--league", choices=[league.value for league in League], required=True)
    live.add_argument("--date", required=True, type=date.fromisoformat, help="UTC calendar date")
    live.add_argument("--dry-run", action="store_true", help="Fetch and validate without opening SQLite")
    live.add_argument("--single-request", action="store_true", help="Dry-run only: one page, no retries")
    stored = subcommands.add_parser("stored-schedule", help="Query persisted schedules")
    stored.add_argument("--date", type=date.fromisoformat, help="UTC calendar date")
    stale = subcommands.add_parser("stale-schedules", help="Report records older than the retrieval threshold")
    stale.add_argument("--hours", type=float, default=24)
    stale.add_argument("--now", help="Explicit timezone-aware reference time for offline reports")
    for command in (importer, live, stored, stale):
        command.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    for command in (stored, stale):
        command.add_argument("--league", choices=[league.value for league in League])
        command.add_argument("--provider")
    args = parser.parse_args(argv)

    if args.command == "parlay-report":
        return run_parlay_report(args, parser)

    if args.command == "kalshi-parlay":
        if args.no_retries and not args.live:
            parser.error("--no-retries requires --live")
        try:
            link = parse_kalshi_url(args.url)
            if args.offline is not None:
                with args.offline.open("rb") as fixture:
                    body = fixture.read(MAX_RESPONSE_BYTES + 1)
                result = extract_parlay(link, decode_metadata(body), source="offline")
            else:
                client = KalshiClient(max_retries=0 if args.no_retries else 2,
                                      max_requests=2 if args.no_retries else 6)
                result = fetch_parlay(link, client)
        except KalshiError as error:
            parser.error(str(error))
        except (OSError, UnicodeError, ValueError, RecursionError):
            parser.error("unable to read valid Kalshi fixture JSON")
        print(json.dumps(asdict(result), indent=2) if args.format == "json" else parlay_summary(result))
        return 0

    if args.command == "import-live-schedule":
        if args.single_request and not args.dry_run:
            parser.error("--single-request requires --dry-run")
        try:
            client = GamesClient(_project_key(), max_retries=0 if args.single_request else 2)
            provider = BALLDONTLIEGamesProvider(League(args.league), client)
            collection = provider.collect_on(args.date, max_pages=1 if args.single_request else None)
            records = [{**asdict(game), "start_time": game.start_time.isoformat()} for game in collection.games]
            for record in records:
                validate_record(record, "balldontlie")
            retrieved = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            imported = 0
            if not args.dry_run:
                with ScheduleStore(args.database) as store:
                    imported = store.import_records(records, "balldontlie", retrieved_at=retrieved)
        except (ProviderError, ValueError) as error:
            parser.error(str(error))
        except (OSError, sqlite3.Error):
            parser.error("unable to access schedule database")
        print(json.dumps({"league": args.league, "date": args.date.isoformat(), "provider": "balldontlie",
                          "dry_run": args.dry_run, "complete": collection.complete,
                          "pages": collection.pages, "validated": len(records), "imported": imported,
                          "excluded": collection.excluded, "retrieved_at": retrieved}, indent=2))
        return 0

    if args.command != "schedule":
        try:
            # These commands never construct a provider/client or load credentials.
            records = json.loads(args.fixture.read_text(encoding="utf-8")) if args.command == "import-schedule" else None
            with ScheduleStore(args.database) as store:
                if args.command == "import-schedule":
                    result = {"imported": store.import_records(records, args.provider, retrieved_at=args.retrieved_at)}
                elif args.command == "stored-schedule":
                    result = store.query(league=args.league, provider=args.provider,
                                         day=args.date.isoformat() if args.date else None)
                else:
                    result = store.stale(hours=args.hours, now=args.now, league=args.league, provider=args.provider)
        except json.JSONDecodeError:
            parser.error("fixture must contain valid JSON")
        except ValueError as error:
            parser.error(str(error))
        except (OSError, UnicodeError, sqlite3.Error):
            parser.error("unable to read fixture or access schedule database")
        print(json.dumps(result, indent=2))
        return 0

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
