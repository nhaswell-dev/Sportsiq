"""Terminal-safe per-leg matching report, without predictions or outcome fields."""

from datetime import timezone
from zoneinfo import ZoneInfo

from sportsiq.reports.parlay import _safe
from sportsiq.matching.nfl import aware_instant


def matching_summary(result):
    lines = [f"Combo {_safe(result['event_ticker'])} | {_safe(str(result['leg_count']))} legs",
             'Coverage: ' + _safe(result['schedule_coverage'])]
    for match in result['matches']:
        game = match['game']
        name = 'none'
        available = 'kickoff unknown'
        source = 'Kalshi metadata; no provider match'
        if game:
            name = f"{game['away']['name']} at {game['home']['name']} (BALLDONTLIE {game['provider_ids']['balldontlie']})"
            available = game['start_time'] + ' UTC / ' + game['start_time_eastern'] + ' ET'
            source = game['time_source']
        else:
            occurrence = match['evidence'].get('source_times', {}).get('occurrence')
            if occurrence is not None:
                instant = aware_instant(occurrence)
                available = 'occurrence unknown (invalid or timezone absent); NOT kickoff'
                if instant is not None:
                    instant = instant.astimezone(timezone.utc)
                    available = (instant.isoformat() + ' UTC / ' + instant.astimezone(ZoneInfo('America/New_York')).isoformat()
                                 + ' ET occurrence only; NOT kickoff')
        lines.extend([
            f"{match['position']:02}. {_safe(match['selection'])} {_safe(match['side'].upper())} | {_safe(match['league'].upper())} | {_safe(match['outcome'])} | game={_safe(name)}",
            f"    time={_safe(available)} | source={_safe(source)}",
            f"    event={_safe(match['event_ticker'])} market={_safe(match['market_ticker'])}",
            '    uncertainty: ' + _safe('; '.join(match['uncertainty'])),
        ])
    lines.append('Missing pregame inputs (all legs): verified kickoff; point-in-time schedule/cutoff; injuries/rosters; team/player features; timestamped prices/rules; cross-leg dependence.')
    return '\n'.join(lines)
