"""Terminal-safe descriptive NFL evidence report, never a predictive recommendation."""

import json

from sportsiq.reports.parlay import _safe


def assessment_summary(result):
    lines = [_safe(result['notice']),
             'NFL offline descriptive assessment | mode=' + _safe(result['mode']),
             'Analysis cutoff: ' + _safe(result['analysis_cutoff']),
             'Per-leg reports only; no combo probability or execution assessment.']
    for leg in result['legs']:
        lines.extend([
            '', _safe(leg['leg_id']) + ': ' + _safe(leg.get('selected_team', leg['selected_team_id']))
            + ' ' + _safe(leg['side']) + ' | ' + _safe(leg['assessment']),
            '  Market: ' + _safe(leg['market_ticker']) + ' | game=' + _safe(leg['game_id']),
            '  Opponent: ' + _safe(leg.get('opponent_team')),
            '  Scheduled: ' + _safe(leg['scheduled_kickoff']) + ' | actual: ' + _safe(leg['actual_kickoff']),
            '  Schedule sources: ' + ', '.join(_safe(s) for s in leg['schedule_source_ids']),
            '  Kickoff sources (chronology only): ' + ', '.join(_safe(s) for s in leg['kickoff_source_ids']),
            '  Coverage: ' + _safe(leg['coverage']),
        ])
        for metric in leg['metrics']:
            lines.extend([
                '  ' + _safe(metric['name']) + ' [' + _safe(metric['status']) + '] | source=' +
                ', '.join(_safe(s) for s in metric['source_ids']),
                '    selected: ' + json.dumps(metric['selected'], ensure_ascii=True, sort_keys=True),
                '    opponent: ' + json.dumps(metric['opponent'], ensure_ascii=True, sort_keys=True),
                '    games: ' + ', '.join(_safe(g) for g in metric['game_ids']),
            ])
        if not leg['metrics']:
            lines.append('  Metrics: unavailable (evidence gates failed)')
        for title, field in (('Evidence for', 'evidence_for'), ('Evidence against', 'evidence_against'),
                             ('Missing', 'missing_data'), ('Uncertainty', 'uncertainty')):
            lines.append('  ' + title + ': ' + ('; '.join(_safe(v) for v in leg[field]) or 'none identified'))
    source_note = ('pinned snapshot verified; no live references fetched'
                   if result.get('snapshot_status') == 'ACCEPTED_OBSERVED_HISTORY'
                   else 'fixture assertions; references are never fetched')
    lines.append('\nSource provenance (' + source_note + '):')
    for source in result['sources']:
        lines.append('  ' + json.dumps(source, ensure_ascii=True, sort_keys=True))
    lines.append('Excluded evidence: ' + str(len(result['excluded'])))
    for excluded in result['excluded']:
        lines.append('  ' + json.dumps(excluded, ensure_ascii=True, sort_keys=True))
    return '\n'.join(lines)
