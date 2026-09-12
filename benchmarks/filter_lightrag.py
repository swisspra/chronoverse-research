"""Reference post-filter over saved actual LightRAG candidates, not native policy."""
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

from benchmarks.temporal import reference_eligible, summarize_run


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    args=parser.parse_args()
    benchmark_run=BenchmarkRun(allow_dirty=args.allow_dirty)
    fixture_path = Path('benchmarks/data/temporal-v1.json')
    fixture = json.loads(fixture_path.read_text())
    source = Path('docs/benchmarks/lightrag-results.json')
    actual = json.loads(source.read_text())
    assert actual['fixture']['sha256'] == sha256(fixture_path.read_bytes()).hexdigest()
    records = {row['id']: row for row in fixture['assertions']}
    queries = {row['id']: row for row in fixture['queries']}
    events = defaultdict(list)
    for event in fixture['events']:
        events[event['assertion_id']].append(event)
    run = {}
    for result in actual['queries']:
        query = queries[result['id']]
        candidates = result['retrieved_assertion_ids']
        assert all(aid in records for aid in candidates)
        run[result['id']] = [aid for aid in candidates
            if reference_eligible(records[aid], query['scope'], events)][:10]
    output = dict(method='LightRAG + reference post-filter', derived_from_sha256=sha256(source.read_bytes()).hexdigest(),
        fixture_sha256=sha256(fixture_path.read_bytes()).hexdigest(),
        protocol='Independent metadata/lifecycle filter applied AFTER actual LightRAG returned 20 candidates; retains native candidate order, then takes 10. No gold labels used. This adapter is not native LightRAG temporal support. Unlike the pre-filtered baselines, it cannot recover eligible records absent from the candidate pool.',
        latency_note='No end-to-end latency reported for this derived saved-result adaptation.',
        summary=summarize_run(run, fixture), rankings=run)
    path = Path('docs/benchmarks/lightrag-filtered-results.json')
    benchmark_run.write_json(path, output)
    print(json.dumps({k:v for k,v in output['summary'].items() if k != 'categories'}, indent=2))


if __name__ == '__main__':
    main()
