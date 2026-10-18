"""Offline schedule persistence using only the standard library."""

import json
import math
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sportsiq.domain.models import GameStatus, League


DEFAULT_DATABASE = Path(__file__).resolve().parents[2] / "data" / "sportsiq.sqlite3"
FIELDS = ("league", "provider", "provider_game_id", "home_id", "home_name",
          "home_abbreviation", "away_id", "away_name", "away_abbreviation",
          "start_time", "status")


def utc_timestamp(value, field: str = "timestamp") -> str:
    try:
        if not isinstance(value, str):
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (ValueError, OverflowError):
        raise ValueError(f"{field} must be a valid timezone-aware ISO 8601 timestamp") from None


def required_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def source_id(value, provider: str, field: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"{field} requires a provider_ids object")
    return required_text(value.get(provider), field)


def validate_record(record, provider: str) -> list:
    if not isinstance(record, dict):
        raise ValueError("expected an object")
    if record.get("league") not in [league.value for league in League]:
        raise ValueError("league must be nfl or nba")
    if record.get("status") not in [status.value for status in GameStatus]:
        raise ValueError("status must be a recognized GameStatus value")
    values = [record["league"], provider, source_id(record.get("provider_ids"), provider, "provider_game_id")]
    for side in ("home", "away"):
        team = record.get(side)
        if not isinstance(team, dict):
            raise ValueError(f"{side} must be a complete team object")
        identifier = source_id(team.get("provider_ids"), provider, f"{side} provider team ID")
        name = required_text(team.get("name"), f"{side} name")
        abbreviation = team.get("abbreviation")
        if abbreviation is not None:
            required_text(abbreviation, f"{side} abbreviation")
        values.extend([identifier, name, abbreviation])
    if values[3] == values[6]:
        raise ValueError("home and away team IDs must be different")
    values.extend([utc_timestamp(record.get("start_time"), "start_time"), record["status"]])
    return values


class ScheduleStore:
    def __init__(self, path: Path = DEFAULT_DATABASE) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY,
                league TEXT NOT NULL CHECK (league IN ('nfl', 'nba')),
                provider TEXT NOT NULL,
                provider_game_id TEXT NOT NULL,
                home_id TEXT NOT NULL,
                home_name TEXT NOT NULL,
                home_abbreviation TEXT,
                away_id TEXT NOT NULL,
                away_name TEXT NOT NULL,
                away_abbreviation TEXT,
                start_time TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN (
                    'scheduled', 'in_progress', 'final', 'postponed', 'canceled',
                    'delayed', 'suspended', 'abandoned', 'unknown')),
                retrieved_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (league, provider, provider_game_id)
            );
            CREATE TABLE IF NOT EXISTS game_changes (
                id INTEGER PRIMARY KEY,
                game_id INTEGER NOT NULL REFERENCES games(id),
                before_json TEXT NOT NULL,
                after_json TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                changed_at TEXT NOT NULL
            );
        """)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    def import_records(self, records: object, provider: str, *, retrieved_at: str | None = None) -> int:
        required_text(provider, "provider")
        if not isinstance(records, list):
            raise ValueError("records must be a JSON array")
        validated = []
        for index, record in enumerate(records, 1):
            try:
                validated.append(validate_record(record, provider))
            except ValueError as error:
                raise ValueError(f"record {index}: {error}") from None
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        retrieved = utc_timestamp(retrieved_at, "retrieved_at") if retrieved_at is not None else now
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            for index, values in enumerate(validated, 1):
                previous = self.connection.execute(
                    "SELECT * FROM games WHERE league = ? AND provider = ? AND provider_game_id = ?",
                    values[:3],
                ).fetchone()
                if previous and retrieved < previous["retrieved_at"]:
                    raise ValueError(f"record {index}: retrieved_at is older than the latest stored observation")
                current = dict(zip(FIELDS, values))
                before = {field: previous[field] for field in FIELDS} if previous else None
                changed = before != current
                updated = now if changed else previous["updated_at"]
                if previous and changed:
                    self.connection.execute(
                        "INSERT INTO game_changes (game_id, before_json, after_json, retrieved_at, changed_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (previous["id"], json.dumps(before), json.dumps(current), retrieved, now),
                    )
                assignments = ", ".join(f"{field} = excluded.{field}" for field in FIELDS[3:])
                self.connection.execute(
                    f"INSERT INTO games ({', '.join(FIELDS)}, retrieved_at, created_at, updated_at) "
                    f"VALUES ({', '.join('?' for _ in range(len(FIELDS) + 3))}) "
                    f"ON CONFLICT (league, provider, provider_game_id) DO UPDATE SET {assignments}, "
                    "retrieved_at = excluded.retrieved_at, updated_at = excluded.updated_at",
                    [*values, retrieved, now, updated],
                )
        return len(records)

    def history(self, game_id: int) -> list[dict]:
        return [{"id": row["id"], "game_id": row["game_id"],
                 "before": json.loads(row["before_json"]), "after": json.loads(row["after_json"]),
                 "retrieved_at": row["retrieved_at"], "changed_at": row["changed_at"]}
                for row in self.connection.execute(
                    "SELECT * FROM game_changes WHERE game_id = ? ORDER BY id", (game_id,))]

    def stale(self, *, hours: float = 24, now: str | None = None,
              league: str | None = None, provider: str | None = None) -> list[dict]:
        if not math.isfinite(hours) or hours < 0:
            raise ValueError("hours must be finite and nonnegative")
        reference = datetime.fromisoformat(utc_timestamp(now, "now")) if now is not None else datetime.now(timezone.utc)
        try:
            cutoff = (reference - timedelta(hours=hours)).isoformat(timespec="microseconds")
        except OverflowError:
            raise ValueError("hours exceeds the supported timestamp range") from None
        return [game for game in self.query(league=league, provider=provider) if game["retrieved_at"] < cutoff]

    def query(self, *, league: str | None = None, provider: str | None = None,
              day: str | None = None) -> list[dict]:
        clauses, values = [], []
        if league is not None:
            clauses.append("league = ?")
            values.append(league)
        if provider is not None:
            clauses.append("provider = ?")
            values.append(provider)
        if day is not None:
            start = datetime.combine(date.fromisoformat(day), datetime.min.time(), timezone.utc)
            clauses.append("start_time >= ? AND start_time < ?")
            values.extend([start.isoformat(timespec="microseconds"),
                           (start + timedelta(days=1)).isoformat(timespec="microseconds")])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM games" + where + " ORDER BY start_time, league, provider, provider_game_id", values)]
