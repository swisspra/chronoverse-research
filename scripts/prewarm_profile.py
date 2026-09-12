#!/usr/bin/env python3
"""Populate derived vectors for one profile/snapshot before interactive use."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='demo')
    parser.add_argument('--db', type=Path, default=ROOT / 'data/chronoverse.sqlite3')
    parser.add_argument('--valid-at')
    parser.add_argument('--known-at')
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error('Database does not exist. Start the app before prewarming a profile.')
    os.environ['CHRONOVERSE_EMBEDDINGS'] = 'semantic'
    from chronoverse.models import QueryRequest
    from chronoverse.profiles import ProfileManager
    scope = {'query': 'prewarm', 'world': 'all', 'plane': 'all', 'perspective': 'all', 'limit': 1}
    if args.valid_at:
        scope['valid_at'] = args.valid_at
    if args.known_at:
        scope['known_at'] = args.known_at
    manager = ProfileManager(args.db)
    try:
        started = time.perf_counter()
        result = manager.query(args.profile, QueryRequest(**scope))
        print(json.dumps({'profile_id': args.profile, 'scope': result['scope'],
                          'eligible_documents_indexed': result['eligible_count'],
                          'seconds': round(time.perf_counter() - started, 3),
                          'note': 'Only this snapshot is warmed; other projected evidence remains lazy. No assertions or lifecycle events are changed.'}))
    finally:
        manager.close()


if __name__ == '__main__':
    main()
