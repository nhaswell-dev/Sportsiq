"""Consolidated discovery/mapping and separately scoped descriptive evidence."""

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import json

from sportsiq.domain.models import League
from sportsiq.matching.nfl import canonical_team, match_nfl_leg
from sportsiq.providers.balldontlie import BALLDONTLIEGamesProvider
from sportsiq.providers.nfl_snapshot import assess_snapshot
from sportsiq.analysis.nfl import _instant


# Explicit example routing, not a general market-to-team or timestamp inference.
HISTORY_ROUTES = {
    'KXNFLGAME-26OCT18ARILAR-LAR': ('rams', '2026-10-18T19:00:00Z'),
    'KXNFLGAME-26OCT19WASSF-SF': ('49ers', '2026-10-19T23:00:00Z'),
}


def _analysis(leg, mapping, snapshot, cutoff):
    result: dict = dict(status='INSUFFICIENT_DATA', cutoff=cutoff, engine_assessment='INSUFFICIENT_DATA',
                  metrics=[], source_provenance=[], completion_provenance=[],
                  missing_evidence=['validated_predictive_method_unavailable', 'injury_and_roster_evidence_unavailable',
                                    'pregame_price_evidence_unavailable', 'cross_leg_dependence_unavailable'],
                  warnings=['Descriptive evidence only; not a supported betting selection.',
                            'Market identity and mapping metadata availability at cutoff remain unverified.'])
    route = HISTORY_ROUTES.get(leg.market_ticker)
    if leg.league != 'nfl':
        result['missing_evidence'].append('statistical_adapter_unavailable')
    elif mapping['outcome'] != 'MATCHED':
        result['missing_evidence'].append('unique_game_mapping_unavailable')
    elif not route or leg.side != 'yes':
        result['missing_evidence'].append('historical_adapter_not_available_for_selection')
    else:
        result['cutoff'] = cutoff or _instant(route[1]).isoformat()
        if snapshot is None:
            result['missing_evidence'].append('historical_snapshot_not_supplied')
            return result
        try:
            history = assess_snapshot(snapshot, cutoff=result['cutoff'], selection=route[0])
        except (AttributeError, IndexError, RecursionError):
            # Malformed local metadata must not escape as a traceback or evidence.
            result['missing_evidence'].append('historical_snapshot_verification_failed')
            return result
        assessed = history['legs'][0]
        result.update(snapshot_status=history['snapshot_status'],
                      snapshot_captured_at=history.get('snapshot_captured_at'),
                      raw_snapshot_sha256=history.get('raw_snapshot_sha256'))
        result['missing_evidence'].extend(assessed['missing_data'])
        result['missing_evidence'].extend(history.get('snapshot_missing_evidence', []))
        result['warnings'].extend(assessed['uncertainty'])
        if history['snapshot_status'] == 'ACCEPTED_OBSERVED_HISTORY':
            if (assessed['market_ticker'] != leg.market_ticker or assessed['side'] != leg.side
                    or canonical_team(assessed['selected_team']) != mapping['evidence']['proposition_team']
                    or {canonical_team(assessed['selected_team']), canonical_team(assessed['opponent_team'])}
                    != set(mapping['evidence']['teams'])
                    or _instant(assessed['scheduled_kickoff']) != _instant(mapping['game']['start_time'])):
                result['missing_evidence'].append('matched_game_assessment_context_conflict')
                return result
            result.update(status='SUPPORTED_EVIDENCE', metrics=assessed['metrics'],
                          source_provenance=history['sources'], completion_provenance=history['completion_provenance'],
                          engine_assessment=assessed['assessment'],
                          assessment_scheduled_kickoff=assessed['scheduled_kickoff'],
                          assessment_actual_kickoff=assessed['actual_kickoff'],
                          coverage=assessed['coverage'])
    result['missing_evidence'] = list(dict.fromkeys(result['missing_evidence']))
    return result


def consolidate(extraction, page, *, snapshot=None, cutoff=None, generated_at=None) -> dict:
    """Reuse pure existing normalization/matching; never open clients or stores."""
    cutoff = _instant(cutoff).isoformat() if cutoff is not None else None
    if not isinstance(page, dict) or not isinstance(page.get('data'), list) or not isinstance(page.get('meta'), dict):
        raise ValueError('invalid NFL Games page')
    # Same normalization-only boundary as sportsiq.matching; never call collect_on.
    provider = BALLDONTLIEGamesProvider(League.NFL, None)  # type: ignore[arg-type]
    games = [provider._normalize(record) for record in page['data']]
    ids = [game.provider_ids['balldontlie'] for game in games]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate provider game identities')
    sources = {str(record['id']): record for record in page['data']}
    rows = []
    for leg in extraction.legs:
        mapping = asdict(match_nfl_leg(leg, games, source_games=sources))
        rows.append(dict(position=leg.position, event_ticker=leg.event_ticker, market_ticker=leg.market_ticker,
                         side=leg.side, league=leg.league if leg.league != 'unsupported' else 'unknown',
                         extractor_league=leg.league, classification_source=leg.classification_source,
                         selection=leg.selection, title=leg.title, matchup=leg.description,
                         source_times=leg.times, mapping=mapping,
                         analysis=_analysis(leg, mapping, snapshot, cutoff)))
    counts = Counter(row['league'] for row in rows)
    return dict(schema_version=1, generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
                original_url=extraction.original_url, event_ticker=extraction.event_ticker,
                market_ticker=extraction.market_ticker, leg_count=len(rows),
                league_counts={key: counts[key] for key in ('nfl', 'nba', 'ncaaf', 'ncaab', 'unknown')},
                original_combo_replay_supported=False, combo_assessment='INSUFFICIENT_DATA',
                analysis_cutoff=cutoff, analysis_scope='common_cutoff_review_not_verified_replay' if cutoff
                else 'independent_per_leg_review_not_original_combo_replay',
                warnings=['Mapping is not evidence readiness or a supported betting selection.',
                          'Independent later leg evidence must not be backdated to the original combo.'],
                schedule_coverage='supplied page only; not verified historical coverage',
                next_cursor=page['meta'].get('next_cursor'), legs=rows)


def consolidated_summary(result):
    """Render the same structured report, escaping every external display value."""
    def display(value):
        return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)

    lines = ['SportsIQ consolidated Kalshi parlay report',
             'URL: ' + display(result['original_url']),
             'Event: ' + display(result['event_ticker']),
             'Market: ' + display(result['market_ticker']),
             'Generated: ' + display(result['generated_at']),
             'Legs / leagues: ' + display(result['leg_count']) + ' / ' + display(result['league_counts']),
             'Analysis scope: ' + display(result['analysis_scope']),
             'Common cutoff (null means separate leg cutoffs): ' + display(result['analysis_cutoff']),
             'Combo assessment: ' + display(result['combo_assessment']),
             'Original combo replay supported: ' + display(result['original_combo_replay_supported']),
             'Provenance: ' + display(result.get('provenance', {})),
             'Schedule coverage / cursor: ' + display(result['schedule_coverage']) + ' / ' + display(result['next_cursor'])]
    lines.extend('Warning: ' + display(warning) for warning in result['warnings'])
    for row in result['legs']:
        mapping, analysis = row['mapping'], row['analysis']
        lines.extend(['', display(row['position']) + '. ' + display(row['league']) + ' ' + display(row['side'])
                      + ' | selection=' + display(row['selection']),
                      '  Event: ' + display(row['event_ticker']), '  Market: ' + display(row['market_ticker']),
                      '  Matchup / proposition rules: ' + display(row['matchup']),
                      '  Classification source: ' + display(row['classification_source']),
                      '  Mapping: ' + display(mapping['outcome']) + ' | analysis: ' + display(analysis['status']),
                      '  Cutoff: ' + display(analysis['cutoff']) + ' | engine selection: ' + display(analysis['engine_assessment']),
                      '  Source timestamps (occurrence is NOT kickoff): ' + display(row['source_times'])])
        if mapping['game']:
            game = mapping['game']
            lines.append('  Mapped game / scheduled UTC / Eastern / actual verified: ' + display({
                key: game[key] for key in ('provider_ids', 'start_time', 'start_time_eastern', 'verified_historical_kickoff')}))
        for metric in analysis['metrics']:
            lines.append('  Metric: ' + display(metric))
        lines.extend(['  Snapshot status / capture: ' + display(analysis.get('snapshot_status')) + ' / '
                      + display(analysis.get('snapshot_captured_at')),
                      '  Sources: ' + display(analysis['source_provenance']),
                      '  Completion evidence (not exact whistles): ' + display(analysis['completion_provenance']),
                      '  Missing evidence: ' + display(analysis['missing_evidence']),
                      '  Mapping warnings: ' + display(mapping['uncertainty']),
                      '  Market metadata gaps: ' + display(mapping['evidence']['gaps']),
                      '  Analysis warnings: ' + display(analysis['warnings'])])
    return '\n'.join(lines)
