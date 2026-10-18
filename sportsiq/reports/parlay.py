"""Human-readable discovery output; provider text is terminal-escaped."""

import json

from sportsiq.domain.parlay import ParlayExtraction


def _safe(value: str | None) -> str:
    return json.dumps(value, ensure_ascii=True)[1:-1] if value is not None else "unknown"


def parlay_summary(result: ParlayExtraction) -> str:
    lines = [f"Kalshi combo: {result.event_ticker}", f"Selected market: {result.market_ticker}",
             f"{result.leg_count} legs | source={result.source} | HTTP attempts={result.requests_made}",
             "Discovery only; historical pregame availability is unverified."]
    for leg in result.legs:
        lines.extend([
            f"{leg.position:02}. {leg.league.upper()} | {leg.side.upper()} | label={_safe(leg.selection)}",
            f"    event={leg.event_ticker} market={leg.market_ticker}",
            f"    proposition: {_safe(leg.title)}",
            f"    description: {_safe(leg.description)}",
        ])
        for label, timestamp in leg.times.items():
            text = _safe(timestamp["value"]) + " (" + timestamp["source"] + ")" if timestamp else "unknown"
            lines.append(f"    {label}: {text}")
        lines.append("    gaps: " + ", ".join(leg.gaps))
    lines.extend(result.warnings)
    return "\n".join(lines)
