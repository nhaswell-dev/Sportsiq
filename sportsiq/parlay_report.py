"""Read-only consolidated parlay CLI; offline saved evidence by default."""

import argparse
import hashlib
import json
from pathlib import Path

from sportsiq.providers.balldontlie import ProviderError
from sportsiq.analysis.nfl import _instant
from sportsiq.providers.kalshi import (
    KalshiClient, MAX_RESPONSE_BYTES, decode_metadata, extract_parlay, fetch_parlay, parse_kalshi_url,
)
from sportsiq.reports.consolidated import consolidate, consolidated_summary

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OFFLINE = ROOT / 'tests/fixtures/nfl_combo_observed.json'
DEFAULT_SNAPSHOT = ROOT / 'data/snapshots/nfl/2026-10-19T053443Z'


def _read(path) -> tuple[dict, dict]:
    path = Path(path)
    with path.open('rb') as stream:
        body = stream.read(MAX_RESPONSE_BYTES + 1)
    value = decode_metadata(body)
    if not isinstance(value, dict):
        raise ValueError('metadata must be an object')
    return value, {'reference': path.resolve().as_uri(), 'sha256': hashlib.sha256(body).hexdigest()}


def _saved_bundle(saved):
    if 'extraction' not in saved:
        return saved, None
    raw = saved['extraction']
    legs = raw['legs']
    if not isinstance(legs, list) or type(raw['leg_count']) is not int or raw['leg_count'] != len(legs):
        raise ValueError('incomplete saved extraction')
    milestones = []
    for leg in legs:
        if leg.get('raw_milestone') is not None and leg['raw_milestone'] not in milestones:
            milestones.append(leg['raw_milestone'])
    # Re-run the original extractor on its saved raw projections, not flattened labels.
    return {'combo_market': raw['raw_combo_market'],
            'underlying_markets': [leg['raw_market'] for leg in legs], 'milestones': milestones}, raw.get('observed_at')


def add_arguments(parser):
    parser.add_argument('--url', required=True, help='Exact combo URL including marketTicker')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--offline', type=Path, help='Saved projection or extractor metadata bundle')
    source.add_argument('--live', action='store_true', help='Explicit public GET-only market discovery; no retries')
    parser.add_argument('--games', type=Path, help='Optional saved NFL Games page; never fetched live')
    parser.add_argument('--snapshot', type=Path, default=DEFAULT_SNAPSHOT, help='Existing pinned historical bundle; never downloaded')
    parser.add_argument('--cutoff', help='Optional common aware cutoff; otherwise the two reviewed example leg cutoffs')
    parser.add_argument('--format', choices=('json', 'summary'), default='json')


def run(args, parser: argparse.ArgumentParser) -> int:
    try:
        link = parse_kalshi_url(args.url)
        if args.cutoff is not None:
            _instant(args.cutoff)
        if args.live:
            saved, schedule_source = _read(DEFAULT_OFFLINE if args.games is None else args.games)
            extraction = fetch_parlay(link, KalshiClient(max_retries=0, max_requests=2))
            market_source = {'mode': 'live', 'reference': link.original_url,
                             'captured_at': extraction.observed_at,
                             'requests_made_this_run': extraction.requests_made}
        else:
            saved, market_source = _read(args.offline or DEFAULT_OFFLINE)
            bundle, captured_at = _saved_bundle(saved)
            extraction = extract_parlay(link, bundle, source='offline')
            market_source.update(mode='offline', captured_at=captured_at, requests_made_this_run=0,
                                 capture_time_policy='declared saved observation, not verified pregame availability')
            schedule_source = {key: market_source[key] for key in ('reference', 'sha256')}
            if args.games is not None:
                saved_games, schedule_source = _read(args.games)
            else:
                saved_games = saved
            saved = saved_games
        page = saved.get('games_page', saved)
        if 'data' not in page:
            page = {'data': [], 'meta': {}}
            schedule_source = {'reference': None, 'coverage': 'no saved NFL Games page supplied'}
        schedule_source.update(captured_at=page.get('verification', {}).get('retrieved_at'),
                               capture_time_policy='declared saved provider observation, not verified pregame availability')
        result = consolidate(extraction, page, snapshot=args.snapshot, cutoff=args.cutoff)
        result['provenance'] = {
            'market': market_source, 'schedule': schedule_source,
            'historical_snapshot_reference': args.snapshot.resolve().as_uri(),
            'market_projection_policy': 'Existing matcher allowlists; no raw outcomes, prices or unknown API fields forwarded',
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError, RecursionError, ProviderError):
        parser.error('invalid or unavailable parlay report inputs; no report generated')
    print(json.dumps(result, indent=2, allow_nan=False) if args.format == 'json' else consolidated_summary(result))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    return run(parser.parse_args(argv), parser)


if __name__ == '__main__':
    raise SystemExit(main())
