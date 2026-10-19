"""Run the offline historical CSV adapter; no source retrieval or real-data approval."""

import argparse
import json
from pathlib import Path

from sportsiq.analysis.__main__ import MAX_FIXTURE_BYTES, _constant, _float, _object
from sportsiq.providers.nfl_history import assess_history
from sportsiq.reports.nfl_assessment import assessment_summary


def _read(path):
    with path.open('rb') as stream:
        body = stream.read(MAX_FIXTURE_BYTES + 1)
    if len(body) > MAX_FIXTURE_BYTES:
        raise ValueError('input too large')
    return body.decode('utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True, help='Local nine-column game CSV projection')
    parser.add_argument('--manifest', type=Path, required=True, help='Local provenance/coverage JSON')
    parser.add_argument('--format', choices=('json', 'summary'), default='json')
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(_read(args.manifest), object_pairs_hook=_object,
                              parse_constant=_constant, parse_float=_float)
        result = assess_history(_read(args.csv), manifest)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        parser.error('invalid offline NFL history input; no lookup performed')
    if args.format == 'json':
        print(json.dumps(result, indent=2, allow_nan=False))
    else:
        print(assessment_summary(result))
        print('Historical CSV adapter:')
        print(json.dumps(result['historical_adapter'], indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
