"""Narrow NFL winner-rule matching. No HTTP, storage, prices, or outcomes."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo

from sportsiq.domain.models import GameStatus, League

EASTERN = ZoneInfo('America/New_York')
# Exact allowlist, not fuzzy matching. Ambiguous city names (LA/NY) are absent.
TEAM_NAMES = {
    'ARI': ('Arizona Cardinals', 'ARI Cardinals', 'Arizona'),
    'LAR': ('Los Angeles Rams', 'LA Rams', 'Los Angeles R'),
    'SF': ('San Francisco 49ers', 'SF 49ers', 'San Francisco'),
    'WAS': ('Washington Commanders', 'WAS Commanders', 'Washington', 'WSH'),
}
ALIASES = {alias.casefold(): code for code, names in TEAM_NAMES.items() for alias in (code, *names)}
RULE = re.compile(r'If (.+) wins the (.+) (vs|at) (.+) Pro Football game originally scheduled for '
                  r'([A-Z][a-z]{2} [0-9]{1,2}, [0-9]{4}), then the market resolves to Yes\.')


@dataclass(frozen=True)
class NFLMatch:
    position: int
    event_ticker: str
    market_ticker: str
    side: str
    selection: str | None
    league: str
    outcome: str
    game: dict | None
    candidates: list[dict]
    evidence: dict
    uncertainty: list[str]
    missing_pregame_inputs: list[str]


def canonical_team(value):
    return ALIASES.get(value.strip().casefold()) if isinstance(value, str) else None


def validate_leg(leg):
    """Validate shapes before consumers dereference optional source evidence."""
    if type(leg.position) is not int or leg.position < 1:
        raise ValueError('invalid position')
    for key in ('event_ticker', 'market_ticker', 'side', 'league', 'classification_source'):
        if not isinstance(getattr(leg, key), str):
            raise ValueError('invalid text')
    for key in ('selection', 'title', 'description'):
        if getattr(leg, key) is not None and not isinstance(getattr(leg, key), str):
            raise ValueError('invalid optional text')
    if not isinstance(leg.gaps, list) or not all(isinstance(g, str) for g in leg.gaps):
        raise ValueError('invalid gaps')
    for record in (leg.times, leg.raw_selection, leg.raw_market):
        if not isinstance(record, dict):
            raise ValueError('invalid source record')
    if leg.raw_milestone is not None and not isinstance(leg.raw_milestone, dict):
        raise ValueError('invalid milestone')
    milestone = leg.raw_milestone or {}
    for key in ('related_event_tickers', 'primary_event_tickers'):
        if key in milestone:
            values = milestone[key]
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ValueError('invalid milestone identities')
    if 'custom_strike' in leg.raw_market and not isinstance(leg.raw_market['custom_strike'], dict):
        raise ValueError('invalid custom strike')
    for record in (leg.raw_selection, leg.raw_market, leg.raw_milestone or {},
                   leg.raw_market.get('custom_strike', {})):
        for key, value in record.items():
            if key in ('event_ticker', 'market_ticker', 'ticker', 'side', 'rules_primary',
                       'rules_secondary', 'yes_sub_title', 'no_sub_title', 'title',
                       'football_team', 'start_date', 'end_date', 'updated_time', 'created_time',
                       'last_updated_ts', 'actual_start_time',
                       'occurrence_datetime', 'open_time', 'close_time',
                       'expected_expiration_time', 'latest_expiration_time', 'expiration_time'):
                if value is not None and not isinstance(value, str):
                    raise ValueError('invalid source text')
    for stamp in leg.times.values():
        if stamp is not None and (not isinstance(stamp, dict)
                or not isinstance(stamp.get('value'), str)
                or not isinstance(stamp.get('source'), str)):
            raise ValueError('invalid timestamp evidence')


def aware_instant(stamp):
    """Return an aware instant or unknown; never infer the host timezone."""
    try:
        instant = datetime.fromisoformat(stamp['value'])
        return instant if instant.tzinfo is not None and instant.utcoffset() is not None else None
    except (KeyError, ValueError, TypeError):
        return None


def _project(record, fields) -> dict:
    """Positive allowlist: unknown provider fields cannot leak outcomes."""
    return {key: value for key, value in record.items()
            if key in fields and (value is None or isinstance(value, (str, int, float, bool)))}


def _market_source(record):
    result = _project(record, ('ticker', 'event_ticker', 'title', 'subtitle', 'yes_sub_title',
                              'no_sub_title', 'rules_primary', 'rules_secondary', 'occurrence_datetime',
                              'updated_time', 'created_time', 'open_time', 'close_time',
                              'expiration_time', 'expected_expiration_time', 'latest_expiration_time'))
    if 'custom_strike' in record:
        result['custom_strike'] = _project(record['custom_strike'], ('football_team',))
    return result


def _milestone_source(record):
    if record is None:
        return None
    result = _project(record, ('id', 'type', 'title', 'start_date', 'end_date', 'last_updated_ts', 'actual_start_time'))
    for key in ('related_event_tickers', 'primary_event_tickers'):
        if key in record:
            result[key] = [v for v in record[key] if isinstance(v, str)]
    return result


def _game_source(record):
    result = _project(record, ('id', 'date', 'status', 'status_state', 'season', 'week', 'postseason'))
    for key in ('home_team', 'visitor_team'):
        if isinstance(record.get(key), dict):
            result[key] = _project(record[key], ('id', 'full_name', 'name', 'abbreviation', 'city', 'conference', 'division'))
    return result


def _snapshot(game, source_games):
    result = asdict(game)
    result['start_time'] = game.start_time.astimezone(timezone.utc).isoformat()
    result['start_time_eastern'] = game.start_time.astimezone(EASTERN).isoformat()
    result['time_source'] = 'balldontlie.games.date (current schedule metadata)'
    result['verified_historical_kickoff'] = None
    source = source_games.get(game.provider_ids.get('balldontlie'))
    result['source_record'] = _game_source(source) if source is not None else None
    result['source_evidence_gap'] = None if source is not None else 'raw provider record not supplied'
    return result


def match_nfl_leg(leg, games, *, team_ids=None, source_games=None):
    """Match explicit rule pair and original date to provider Eastern game day.

    `vs` is unordered; only `at` conveys away/home. Rule dates are calendar
    dates, not kickoff instants. Occurrence/expiration/ticker dates are never
    substitutes for kickoff. Caller must supply its schedule coverage context.
    """
    validate_leg(leg)
    team_ids = dict(team_ids or {})
    source_games = source_games or {}
    evidence = {'rules_primary': leg.description, 'date_source': 'market.rules_primary',
                'date_policy': 'original rule calendar date compared to America/New_York schedule day',
                'classification_source': leg.classification_source,
                'source_times': {key: _project(value, ('value', 'source')) if value is not None else None
                                 for key, value in leg.times.items()
                                 if key in ('scheduled_start', 'occurrence', 'market_updated', 'schedule_updated', 'actual_start')},
                'kalshi_team_id': leg.raw_market.get('custom_strike', {}).get('football_team')}
    evidence.update(raw_selection=_project(leg.raw_selection, ('event_ticker', 'market_ticker', 'side')),
                    raw_market=_market_source(leg.raw_market), raw_milestone=_milestone_source(leg.raw_milestone),
                    gaps=list(leg.gaps))
    uncertainty = ['historical_kickoff_unverified', 'pregame_availability_unverified']
    occurrence = leg.times.get('occurrence')
    if occurrence is not None and aware_instant(occurrence) is None:
        uncertainty.append('invalid occurrence metadata; not used for matching')
    missing = ['verified historical kickoff', 'point-in-time schedule and analysis cutoff',
               'pregame injuries/rosters', 'pregame team/player features',
               'timestamped pregame prices and settlement rules', 'cross-leg dependence inputs']

    def finish(outcome, candidates=(), reason=None):
        snapshots = [_snapshot(g, source_games) for g in candidates]
        return NFLMatch(leg.position, leg.event_ticker, leg.market_ticker, leg.side,
                        leg.selection, leg.league, outcome,
                        snapshots[0] if outcome == 'MATCHED' else None, snapshots, evidence,
                        uncertainty + ([reason] if reason else []), missing)

    if leg.league != 'nfl' or not leg.event_ticker.startswith('KXNFLGAME-'):
        return finish('UNSUPPORTED', reason='only NFL game-winner series supported')
    checks = [(leg.raw_market.get('rules_primary'), leg.description),
              (leg.raw_market.get('ticker'), leg.market_ticker),
              (leg.raw_market.get('event_ticker'), leg.event_ticker),
              (leg.raw_selection.get('event_ticker'), leg.event_ticker),
              (leg.raw_selection.get('market_ticker'), leg.market_ticker),
              (leg.raw_selection.get('side'), leg.side)]
    if any(source is None or source != flattened for source, flattened in checks):
        return finish('UNSUPPORTED', reason='conflicting or missing source evidence')
    if leg.raw_milestone is not None:
        milestone_events = (leg.raw_milestone.get('related_event_tickers', [])
                            + leg.raw_milestone.get('primary_event_tickers', []))
        if leg.event_ticker not in milestone_events:
            return finish('UNSUPPORTED', reason='conflicting or missing milestone event identity')
    rule = RULE.fullmatch(leg.description or '')
    if rule is None:
        return finish('UNSUPPORTED', reason='unrecognized NFL winner-rule template')
    selected, first, relation, second, day_text = rule.groups()
    teams = [canonical_team(first), canonical_team(second)]
    proposition = canonical_team(selected)
    if canonical_team(leg.selection) != proposition:
        return finish('UNSUPPORTED', reason='conflicting or missing source evidence')
    if (None in teams or teams[0] == teams[1] or proposition not in teams
            or canonical_team(leg.raw_market.get('yes_sub_title')) != proposition
            or leg.side not in ('yes', 'no')):
        return finish('UNSUPPORTED', reason='unknown or inconsistent team identifiers')
    try:
        day = datetime.strptime(day_text, '%b %d, %Y').date()
    except ValueError:
        return finish('NOT_FOUND', reason='invalid original rule date')
    evidence.update(teams=teams, proposition_team=proposition, original_date=day.isoformat(),
                    home_context=teams[1] if relation == 'at' else 'unspecified (vs)')
    evidence['known_balldontlie_team_ids'] = team_ids

    evidence['rejected_games'] = []
    scheduled = None
    if leg.raw_milestone is not None and leg.times.get('scheduled_start') is not None:
        raw_start = aware_instant({'value': leg.raw_milestone.get('start_date')})
        flattened_start = aware_instant(leg.times['scheduled_start'])
        if raw_start is None or raw_start != flattened_start:
            return finish('UNSUPPORTED', reason='conflicting milestone scheduled start evidence')
    if leg.raw_milestone is not None and leg.raw_milestone.get('start_date') is not None:
        scheduled = aware_instant({'value': leg.raw_milestone['start_date']})
        if scheduled is None:
            return finish('NOT_FOUND', reason='invalid scheduled start evidence')
    if leg.times.get('scheduled_start'):
        try:
            scheduled = datetime.fromisoformat(leg.times['scheduled_start']['value'])
            if scheduled.tzinfo is None or scheduled.utcoffset() is None:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            return finish('NOT_FOUND', reason='invalid scheduled start evidence')
    candidates = []
    for game in games:
        if game.league != League.NFL or not game.provider_ids.get('balldontlie'):
            continue
        home, away = canonical_team(game.home.name), canonical_team(game.away.name)
        if set((home, away)) != set(teams):
            continue
        conflict = False
        for team, code in ((game.home, home), (game.away, away)):
            if (team.abbreviation and canonical_team(team.abbreviation) != code
                    or not team.provider_ids.get('balldontlie')
                    or code in team_ids and team.provider_ids.get('balldontlie') != team_ids[code]):
                conflict = True
        if conflict:
            evidence['rejected_games'].append({**_snapshot(game, source_games), 'rejection_reason': 'provider identity conflict'})
            if 'provider identity conflict' not in uncertainty:
                uncertainty.append('provider identity conflict')
            continue
        if relation == 'at' and (away, home) != tuple(teams):
            continue
        if game.start_time.astimezone(EASTERN).date() != day:
            evidence['rejected_games'].append({**_snapshot(game, source_games), 'rejection_reason': 'original/provider date conflict'})
            if 'original/provider date conflict' not in uncertainty:
                uncertainty.append('original/provider date conflict')
            continue
        if scheduled is not None and scheduled != game.start_time:
            evidence['rejected_games'].append({**_snapshot(game, source_games), 'rejection_reason': 'scheduled/provider time conflict'})
            if 'scheduled/provider time conflict' not in uncertainty:
                uncertainty.append('scheduled/provider time conflict')
            continue
        candidates.append(game)
    if len(candidates) == 1:
        if occurrence is not None:
            instant = aware_instant(occurrence)
            if instant is not None and instant != candidates[0].start_time:
                uncertainty.append('occurrence differs from provider schedule; occurrence is not kickoff')
        if candidates[0].status in (GameStatus.POSTPONED, GameStatus.CANCELED, GameStatus.DELAYED,
                                    GameStatus.SUSPENDED, GameStatus.ABANDONED, GameStatus.UNKNOWN):
            return finish('AMBIGUOUS', candidates, 'schedule lifecycle requires verification')
        return finish('MATCHED', candidates)
    return finish('AMBIGUOUS' if candidates else 'NOT_FOUND', candidates,
                  'multiple exact candidates' if candidates else 'no pair/date/context match in supplied coverage')
