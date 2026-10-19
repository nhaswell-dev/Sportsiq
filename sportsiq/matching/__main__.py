"""Offline-only consumer of existing extractor JSON and a saved NFL Games page."""

import argparse
from dataclasses import asdict
from pathlib import Path
import json

from sportsiq.domain.models import League
from sportsiq.domain.parlay import ParlayLeg
from sportsiq.matching.nfl import match_nfl_leg, validate_leg
from sportsiq.providers.balldontlie import BALLDONTLIEGamesProvider, ProviderError
from sportsiq.providers.kalshi import decode_metadata, MAX_RESPONSE_BYTES
from sportsiq.reports.nfl_matching import matching_summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extraction', type=Path, required=True)
    parser.add_argument('--games', type=Path, required=True, help='Saved BALLDONTLIE NFL Games page; no network')
    parser.add_argument('--format', choices=('json', 'summary'), default='summary')
    args = parser.parse_args(argv)
    try:
        payloads = []
        for path in (args.extraction, args.games):
            with path.open('rb') as stream:
                payloads.append(decode_metadata(stream.read(MAX_RESPONSE_BYTES + 1)))
        extracted, page = payloads
        if not isinstance(extracted, dict) or not isinstance(page, dict) or not isinstance(extracted['legs'], list):
            raise ValueError('invalid input records')
        legs = [ParlayLeg(**record) for record in extracted['legs']]
        for leg in legs:
            validate_leg(leg)
        for key in ('source', 'observed_at', 'original_url', 'event_ticker', 'market_ticker'):
            if not isinstance(extracted[key], str):
                raise ValueError('invalid extraction text')
        if type(extracted['leg_count']) is not int or not 1 <= len(legs) <= 100 or extracted['leg_count'] != len(legs):
            raise ValueError('invalid leg count')
        if len({leg.market_ticker for leg in legs}) != len(legs):
            raise ValueError('duplicate leg identities')
        if not isinstance(page['data'], list) or not isinstance(page['meta'], dict):
            raise ValueError('invalid games page')
        # Only pure normalization is reused. No client/credential/store is constructed.
        provider = BALLDONTLIEGamesProvider(League.NFL, None)
        games = [provider._normalize(record) for record in page['data']]
        game_ids = [game.provider_ids['balldontlie'] for game in games]
        if len(set(game_ids)) != len(game_ids):
            raise ValueError('duplicate provider game identities')
        source_games = {str(record['id']): record for record in page['data']}
        result = {k: extracted[k] for k in ('source', 'observed_at', 'original_url', 'event_ticker', 'market_ticker', 'leg_count')}
        result.update(schedule_coverage='supplied page only; not verified historical coverage',
                      next_cursor=page['meta'].get('next_cursor'),
                      matches=[asdict(match_nfl_leg(leg, games, source_games=source_games)) for leg in legs])
    except (OSError, ValueError, TypeError, KeyError, ProviderError):
        parser.error('invalid extraction or NFL Games page; no lookup performed')
    print(json.dumps(result, indent=2) if args.format == 'json' else matching_summary(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
