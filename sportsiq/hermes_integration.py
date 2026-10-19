"""Narrow, read-only JSON invocation boundary for Hermes; no gateway hooks."""

from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

from sportsiq.providers.kalshi import decode_metadata, parse_kalshi_url

ROOT = Path('/home/hermesdev/development/sportsiq')
PYTHON = ROOT / '.venv/bin/python'
OFFLINE = ROOT / 'tests/fixtures/nfl_combo_observed.json'
SNAPSHOT = ROOT / 'data/snapshots/nfl/2026-10-19T053443Z'


def validate_request(request):
    """Preserve exact identifiers; reject ambiguous encodings and extra controls."""
    if (not isinstance(request, dict) or not {'url'} <= request.keys()
            or request.keys() - {'url', 'mode'}):
        raise ValueError('invalid request')
    url, mode = request['url'], request.get('mode', 'offline')
    link = parse_kalshi_url(url)
    parts = urlsplit(url)
    fields = parts.query.split('&')
    names = [field.split('=', 1)[0] for field in fields]
    if (parts.netloc != 'kalshi.com' or mode not in ('offline', 'live-read-only')
            or len(names) != len(set(names))
            or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*=[A-Za-z0-9_.~-]+', field, re.ASCII)
                   for field in fields)):
        raise ValueError('invalid request')
    return link.original_url, mode


def invoke(request):
    """Run only the existing consolidated CLI, never a caller-supplied command."""
    url, mode = validate_request(request)
    argv = [str(PYTHON), '-E', '-s', '-B', '-m', 'sportsiq', 'parlay-report',
            '--url', url, '--format', 'json', '--snapshot', str(SNAPSHOT)]
    argv.extend(['--offline', str(OFFLINE)] if mode == 'offline' else ['--live'])
    try:
        child = subprocess.run(argv, cwd=ROOT, env={'LANG': 'C.UTF-8'}, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, encoding='utf-8', timeout=35,
                               check=False, shell=False)
        if child.returncode != 0:
            raise ValueError()
        report = decode_metadata(child.stdout.encode('utf-8'))
        link = parse_kalshi_url(url)
        if (report['schema_version'] != 1 or report['original_url'] != url
                or report['event_ticker'] != link.event_ticker or report['market_ticker'] != link.market_ticker
                or type(report['leg_count']) is not int or not 1 <= report['leg_count'] <= 100
                or len(report['legs']) != report['leg_count']
                or report['combo_assessment'] != 'INSUFFICIENT_DATA'
                or report['original_combo_replay_supported'] is not False):
            raise ValueError()
        counts = Counter(row['league'] for row in report['legs'])
        if (counts.keys() - {'nfl', 'nba', 'ncaaf', 'ncaab', 'unknown'}
                or report['league_counts'] != {key: counts[key] for key in ('nfl', 'nba', 'ncaaf', 'ncaab', 'unknown')}
                or any(row['analysis']['engine_assessment'] != 'INSUFFICIENT_DATA'
                       or row['analysis']['status'] not in ('SUPPORTED_EVIDENCE', 'INSUFFICIENT_DATA')
                       for row in report['legs'])
                or report['provenance']['market']['mode'] != ('offline' if mode == 'offline' else 'live')):
            raise ValueError()
        return report
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise ValueError('SportsIQ invocation failed') from None


def response(report):
    """Keep complete evidence in JSON; render bounded, ASCII, plain-text messages."""
    def display(value):
        return json.dumps(value, ensure_ascii=True, allow_nan=False)

    legs = report['legs']
    shared = set.intersection(*(set(row['analysis']['missing_evidence']) for row in legs))
    market, schedule = report['provenance']['market'], report['provenance']['schedule']
    lines = [
        'Legs: ' + str(report['leg_count']) + ' | ' + ', '.join(
            key + '=' + str(value) for key, value in report['league_counts'].items()),
        'Combo assessment: ' + display(report['combo_assessment']),
        'Original combo replay: not verified; independent leg evidence is not a combo replay.',
        'SUPPORTED_EVIDENCE means descriptive history only, not a supported betting selection.',
        'Generated: ' + display(report['generated_at']),
        'Market mode/captured: ' + display(market['mode']) + ' / ' + display(market.get('captured_at')),
        'Schedule captured: ' + display(schedule.get('captured_at')) + ' (saved page only)',
        'Missing capture timestamps remain unknown; saved observations do not prove pregame availability.',
        'Shared missing data: ' + display(sorted(shared)),
    ]
    for row in legs:
        analysis, mapping = row['analysis'], row['mapping']
        lines.extend([
            str(row['position']) + '. ' + display(row['league']) + ' ' + display(row['side'])
            + ' ' + display(row['selection']) + ' | ' + display(row['market_ticker']),
            '  Match=' + display(mapping['outcome']) + '; evidence=' + display(analysis['status'])
            + '; engine=' + analysis['engine_assessment'],
            '  verified prior records=' + str(len(analysis['completion_provenance']))
            + '; snapshot captured=' + display(analysis.get('snapshot_captured_at'))
            + '; cutoff=' + display(analysis['cutoff']),
            '  Additional missing data: ' + display(sorted(set(analysis['missing_evidence']) - shared))
            + '; market gaps=' + display(mapping['evidence']['gaps']),
        ])
    lines.append('Full metrics, source/completion provenance and per-leg timestamps are in report JSON.')
    prefix = 'SportsIQ | Not a betting recommendation.\n'
    messages, current = [], prefix
    for line in lines:
        # ASCII escaping makes character counts equal Telegram UTF-16 units.
        while line:
            space = 3500 - len(current) - 1
            if len(line) <= space:
                current += line + '\n'
                break
            if current != prefix:
                messages.append(current.rstrip('\n'))
                current = prefix
            else:
                current += line[:space]
                messages.append(current)
                current, line = prefix, line[space:]
    if current != prefix:
        messages.append(current.rstrip('\n'))
    return dict(ok=True, schema_version=1, messages=messages, text='\n\n'.join(messages), report=report)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def main():
    """Read one bounded JSON object from stdin, never URL-bearing shell syntax."""
    try:
        raw = sys.stdin.read(8193)
        if len(raw) > 8192:
            raise ValueError()
        request = json.loads(raw, object_pairs_hook=_unique_object)
        validate_request(request)
        result = response(invoke(request))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        print(json.dumps(dict(ok=False, schema_version=1, error='invalid_request_or_report_unavailable',
                              text='SportsIQ report unavailable; check URL and local evidence inputs.')))
        return 2
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
