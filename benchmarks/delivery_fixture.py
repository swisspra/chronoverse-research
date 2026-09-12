"""Schema-only migration of a frozen historical fixture; no new gold authorship.

All ranking text and manually authored gold remain byte-for-byte string values.
The migration manifest records the exact old and new file hashes.
"""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_FIXTURE = ROOT / 'docs/benchmarks-observer/fixture.json'
HISTORICAL_HASH = '20ce2a70ee5208549e93d27d29b04d0c5dd4b3b6021bbc01dae7a9bd40f03cd7'


def migrate_schema(value):
    keys = {'observer_id': 'recipient_id', 'observer_at': 'received_by',
            'observer_view': 'delivery_view', 'Observer projection': 'Delivery projection'}
    if isinstance(value, dict):
        return {keys.get(k, k): migrate_schema(v) for k, v in value.items()}
    if isinstance(value, list):
        return [migrate_schema(v) for v in value]
    if value in ('observer-red', 'observer-blue', 'observer-green'):
        return value.replace('observer-', 'recipient-')
    return 'delivery' if value == 'observer' else value


def generate():
    raw = HISTORICAL_FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HISTORICAL_HASH
    return migrate_schema(json.loads(raw))


def main():
    target = ROOT / 'benchmarks/data/delivery-v1.json'
    target.write_text(json.dumps(generate(), indent=2, ensure_ascii=False) + '\n')
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
