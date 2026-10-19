"""Offline-only NFL assessment of explicit local analysis fixtures."""

import argparse
import json
import math
from pathlib import Path

from sportsiq.analysis.nfl import assess_nfl
from sportsiq.reports.nfl_assessment import assessment_summary

MAX_FIXTURE_BYTES = 2 * 1024 * 1024


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('nonfinite JSON number')


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite JSON number')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True, help='Local analysis JSON; no live mode')
    parser.add_argument('--format', choices=('json', 'summary'), default='json')
    args = parser.parse_args(argv)
    try:
        with args.fixture.open('rb') as stream:
            body = stream.read(MAX_FIXTURE_BYTES + 1)
        if len(body) > MAX_FIXTURE_BYTES:
            raise ValueError('fixture too large')
        payload = json.loads(body.decode('utf-8'), object_pairs_hook=_object,
                             parse_constant=_constant, parse_float=_float)
        result = assess_nfl(payload)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        parser.error('invalid offline NFL analysis fixture; no lookup performed')
    print(json.dumps(result, indent=2, allow_nan=False) if args.format == 'json' else assessment_summary(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
