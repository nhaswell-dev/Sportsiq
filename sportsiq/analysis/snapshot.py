"""Offline, code-approved observed-complete NFL snapshot assessments."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from sportsiq.providers.nfl_snapshot import assess_snapshot
from sportsiq.reports.nfl_assessment import assessment_summary


def snapshot_summary(result):
    lines = [assessment_summary(result),
             '\nReport generated: ' + result['report_generated_at'],
             'Snapshot status: ' + result['snapshot_status'],
             'Observed completion provenance (not exact completion timestamps):']
    for record in result['completion_provenance']:
        lines.append('  ' + json.dumps(record, sort_keys=True, ensure_ascii=True))
    if 'snapshot_captured_at' in result:
        lines.extend(['Capture: ' + result['snapshot_captured_at'],
                      'Raw SHA-256: ' + result['raw_snapshot_sha256']])
    if result['snapshot_status'] == 'BLOCKED':
        lines.append('Missing snapshot evidence: ' + json.dumps(result['snapshot_missing_evidence']))
    else:
        lines.extend(['Inventory: ' + result['reviewed_inventory'],
                      'License review: ' + result['license_review']])
    return '\n'.join(line.rstrip() for line in '\n'.join(lines).splitlines())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--cutoff', required=True, help='Explicit timezone-aware pregame cutoff')
    parser.add_argument('--selection', choices=('49ers', 'rams'), default='49ers')
    parser.add_argument('--format', choices=('json', 'summary'), default='json')
    args = parser.parse_args(argv)
    try:
        result = assess_snapshot(args.snapshot, cutoff=args.cutoff, selection=args.selection)
    except (ValueError, TypeError, OverflowError, RecursionError):
        parser.error('invalid observed snapshot request; no lookup performed')
    result['report_generated_at'] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(result, indent=2, allow_nan=False) if args.format == 'json' else snapshot_summary(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
