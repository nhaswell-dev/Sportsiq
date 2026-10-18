"""Discovery records, separate from schedule Game/League and predictive models."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParlayLeg:
    position: int
    event_ticker: str
    market_ticker: str
    side: str
    league: str
    classification_source: str
    selection: str | None
    title: str | None
    description: str | None
    times: dict[str, dict[str, str] | None]
    gaps: list[str]
    raw_selection: dict[str, Any]
    raw_market: dict[str, Any]
    raw_milestone: dict[str, Any] | None


@dataclass(frozen=True)
class ParlayExtraction:
    original_url: str
    event_ticker: str
    market_ticker: str
    source: str
    observed_at: str
    requests_made: int
    leg_count: int
    legs: list[ParlayLeg]
    raw_combo_market: dict[str, Any]
    warnings: list[str]
