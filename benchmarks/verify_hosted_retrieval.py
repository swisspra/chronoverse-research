"""Read-only reconstruction of hosted ranking metrics against public qrels."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path


def verify(result: dict, corpus_ids: set[str], qrels: dict[str, dict[str, int]]) -> dict:
    data = result['dataset']
    assert result['status'] == 'complete'
    assert data['corpus_count'] == len(corpus_ids), 'Corpus count mismatch'
    assert data['query_count'] == len(qrels), 'Query count mismatch'
    assert set(data['rankings']) == set(qrels), 'Query coverage mismatch'
    assert set(data['per_query_ndcg']) == set(qrels), 'Per-query metric coverage mismatch'
    values = []
    for qid, gold in qrels.items():
        ranking = data['rankings'][qid]
        assert len(ranking) == len(set(ranking)), 'Duplicate ranking IDs'
        assert len(ranking) <= 100 and set(ranking) <= corpus_ids, 'Invalid ranking IDs'
        assert qid not in ranking, 'Self-document was not excluded'
        ideal = sum(grade / math.log2(index + 2) for index, grade in
                    enumerate(sorted((v for v in gold.values() if v > 0), reverse=True)[:10]))
        gain = sum(max(gold.get(did, 0), 0) / math.log2(index + 2)
                   for index, did in enumerate(ranking[:10]))
        value = gain / ideal if ideal else 0.0
        assert math.isclose(value, data['per_query_ndcg'][qid], abs_tol=1e-12), 'Per-query nDCG mismatch'
        values.append(value)
    aggregate = sum(values) / len(values)
    assert math.isclose(aggregate, data['nDCG@10'], abs_tol=1e-12), 'Aggregate nDCG mismatch'
    for label in ('document_embeddings', 'query_embeddings'):
        metadata = data[label]
        assert metadata['model'] == 'text-embedding-3-large' and metadata['dimensions'] == 3072
        assert metadata['max_input_tokens'] == 512 and metadata['tokenizer'] == 'cl100k_base'
    provenance = result['provenance']
    assert provenance['predictions_committed_exactly'] is True
    if provenance['git_dirty']:
        assert provenance.get('allow_dirty') is False
        assert provenance.get('generated_outputs_dirty_exemption') is True
        assert set(provenance['git_dirty_paths']) <= set(provenance['generated_outputs'])
        assert all(path.startswith('docs/benchmarks-next/hosted-') and path.endswith('-results.json')
                   for path in provenance['git_dirty_paths']), 'Unexpected dirty source'
    assert provenance['git_commit'] and provenance['predictions_commit'] and provenance['predictions_sha256']
    calls = result['accounting']['calls'].values()
    assert sum(call['reserved_tokens'] for call in calls) == result['accounting']['reserved_tokens']
    complete = [call for call in calls if call['status'] == 'complete']
    for call in complete:
        assert call['response_model'] == 'text-embedding-3-large'
        assert 0 <= call['usage']['total_tokens'] <= call.get('current_reservation',call['reserved_tokens'])
        if call.get('prior_attempts'):
            assert len(call['prior_attempts']) == 1
            prior = call['prior_attempts'][0]
            assert prior['status'] == 'failed_or_uncertain' and prior['error_type'] == 'TimeoutError'
            assert call['reserved_tokens'] == prior['reserved_tokens'] + call['current_reservation']
    prior_uncertain = sum(prior['status'] != 'complete' for call in calls
                          for prior in call.get('prior_attempts', []))
    return {'queries_verified': len(values), 'nDCG@10': aggregate,
            'cumulative_completed_requests': len(complete),
            'cumulative_observed_tokens': sum(call['usage']['total_tokens'] for call in complete),
            'prior_uncertain_attempts': prior_uncertain,
            'unresolved_requests': prior_uncertain + sum(call['status'] != 'complete' for call in calls)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('result', type=Path)
    parser.add_argument('--corpus-dir', type=Path, required=True)
    args = parser.parse_args()
    original = args.result.read_bytes()
    raw = gzip.decompress(original) if args.result.suffix == '.gz' else original
    result = json.loads(raw)
    ids = {json.loads(line)['_id'] for line in (args.corpus_dir / 'corpus.jsonl').read_text().splitlines()}
    qrels = {}
    for line in (args.corpus_dir / 'qrels/test.tsv').read_text().splitlines()[1:]:
        qid, did, grade = line.split('\t')
        qrels.setdefault(qid, {})[did] = int(grade)
    print(json.dumps(verify(result, ids, qrels) | {'raw_sha256': hashlib.sha256(raw).hexdigest()}))


if __name__ == '__main__':
    main()
