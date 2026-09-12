"""Recompute completed round-two artifacts with a second implementation, read-only by default."""
from __future__ import annotations

import csv
import argparse
import hashlib
import json
import math

import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/benchmarks-v2'


def read(name):
    return json.loads((OUT / name).read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(run, labels):
    # Separate linear-gain implementation; do not import the benchmark scorer.
    sums = dict.fromkeys(('ndcg@10', 'recall@10', 'mrr@10'), 0.0)
    for qid, judgments in labels.items():
        positive = {d: r for d, r in judgments.items() if r > 0}
        top = run[qid][:10]
        ideal = sum(r / math.log2(i + 2) for i, r in enumerate(sorted(positive.values(), reverse=True)[:10]))
        gain = sum(positive.get(d, 0) / math.log2(i + 2) for i, d in enumerate(top))
        sums['ndcg@10'] += gain / ideal if ideal else 0
        sums['recall@10'] += len(set(top) & positive.keys()) / len(positive) if positive else 0
        sums['mrr@10'] += next((1 / (i + 1) for i, d in enumerate(top) if d in positive), 0)
    return {key: value / len(labels) for key, value in sums.items()}


def verify(directory=OUT, data_dir=ROOT / '.benchmark-data'):
    OUT = Path(directory)
    data_dir = Path(data_dir)
    def read(name):
        return json.loads((OUT / name).read_text())
    labels_scifact = {}
    with (data_dir / 'scifact/qrels/test.tsv').open() as handle:
        for row in csv.DictReader(handle, delimiter='\t'):
            labels_scifact.setdefault(row['query-id'], {})[row['corpus-id']] = int(row['score'])
    index = read('index-results.json')
    assert index['preservation']['identical_top10_ids'] == 300
    assert index['preservation']['reopened_identical_ids_and_scores'] == 300
    fresh = index['phases']['fresh']['per_query']
    reopened = index['phases']['reopened']['per_query']
    assert set(fresh) == set(reopened) and len(fresh) == 300
    for qid in fresh:
        assert fresh[qid]['ids'] == reopened[qid]['ids']
        assert fresh[qid]['scores'] == reopened[qid]['scores']
    for phase in ('fresh', 'reopened'):
        actual = metrics({qid: row['ids'] for qid,row in index['phases'][phase]['per_query'].items()}, labels_scifact)
        for key,value in actual.items():
            assert abs(value-index['phases'][phase]['metrics'][key]) < 1e-12, f'{phase} {key} mismatch'
    for name, expected in index['production_source_sha256'].items():
        assert digest(OUT / 'source/persistent-index' / name) == expected
    for name in ('optimization-results.json', 'lexical-optimization-results.json'):
        result = read(name)
        assert result['status'] == 'complete'
        assert result['preservation']['compared_queries'] == 300
        assert result['preservation']['identical_ids_and_scores'] == 300
        assert set(result['per_query']) == set(fresh)
        for key,value in metrics({qid:row['ids'] for qid,row in result['per_query'].items()},labels_scifact).items():
            assert abs(value-result['metrics'][key]) < 1e-12, f'{name} {key} mismatch'
        for qid, row in result['per_query'].items():
            assert row['ids'] == fresh[qid]['ids'] and row['scores'] == fresh[qid]['scores']

    cross = read('cross-domain-results.json')
    provenance = cross['metadata_correction']
    assert digest(OUT / provenance['executed_source']) == cross['script_sha256']
    assert digest(OUT / provenance['original_result']) == provenance['original_result_sha256']
    original = read(provenance['original_result'])
    for field in ('datasets', 'models', 'runtime', 'macro_average_equal_weight_per_dataset'):
        assert cross[field] == original[field]
    counts = {'scifact': (5183, 300), 'nfcorpus': (3633, 323), 'fiqa': (57638, 648)}
    assert set(cross['datasets']) == set(counts)
    for name, (documents, queries) in counts.items():
        result = cross['datasets'][name]
        assert (result['corpus_count'], result['test_query_count']) == (documents, queries)
        folder = data_dir / 'v2' / name / name
        doc_ids = {json.loads(line)['_id'] for line in (folder / 'corpus.jsonl').open()}
        labels = {}
        with (folder / 'qrels/test.tsv').open() as handle:
            for row in csv.DictReader(handle, delimiter='\t'):
                labels.setdefault(row['query-id'], {})[row['corpus-id']] = int(row['score'])
        assert len(doc_ids) == documents and len(labels) == queries
        assert len(result['systems']) == 6
        for system in result['systems'].values():
            run = system['rankings']
            assert set(run) == set(labels)
            for qid, ranked in run.items():
                assert len(ranked) == len(set(ranked)) == 100
                assert set(ranked) <= doc_ids and qid not in ranked
            recomputed = metrics(run, labels)
            for key, value in recomputed.items():
                assert abs(value - system['metrics'][key]) < 1e-12
        for model_name, model in result['vector_cache'].items():
            for kind, metadata in model.items():
                assert metadata['rows'] == (documents if kind == 'documents' else queries)
                assert metadata['dtype'] == 'float32' and metadata['normalized']
                path = data_dir / 'v2' / f'{name}-{model_name}-{kind}.npy'
                assert digest(path) == metadata['array_sha256']
                matrix = np.load(path, mmap_mode='r')
                assert matrix.shape == (metadata['rows'], 384) and matrix.dtype == np.float32
                for start in range(0, len(matrix), 4096):
                    chunk = matrix[start:start + 4096]
                    assert np.isfinite(chunk).all()
                    assert np.allclose(np.linalg.norm(chunk, axis=1), 1, atol=1e-5)
    temporal = read('temporal-results.json')
    assert digest(ROOT / 'benchmarks/data/temporal-v2.json') == temporal['fixture_sha256']
    assert digest(OUT / 'temporal-fixture.json') == temporal['fixture_sha256']
    test = [q for q in temporal['queries'] if q['split'] == 'test']
    dev = [q for q in temporal['queries'] if q['split'] == 'dev']
    assert len(test) == 114 and len(dev) == 40
    assert len([q for q in test if not q['gold_assertion_ids']]) == 42
    assert not ({q['family'] for q in dev} & {q['family'] for q in test})
    rerank = read('rerank-results.json')
    rows = rerank['per_query']
    labels = {}
    folder = data_dir / 'scifact'
    with (folder / 'qrels/test.tsv').open() as handle:
        for row in csv.DictReader(handle, delimiter='\t'):
            labels.setdefault(row['query-id'], {})[row['corpus-id']] = int(row['score'])
    doc_ids = {json.loads(line)['_id'] for line in (folder / 'corpus.jsonl').open()}
    assert len(rows) == len({row['id'] for row in rows}) == 300
    assert {row['id'] for row in rows} == set(labels)
    for row in rows:
        assert len(row['candidates']) == len(set(row['candidates'])) == 50
        assert len(row['reranked']) == len(set(row['reranked'])) == 50
        assert set(row['candidates']) == set(row['reranked'])
        assert set(row['candidates']) <= doc_ids
    for field, method in [('candidates', 'rrf_minilm_top50'), ('reranked', 'rrf_minilm_cross_encoder')]:
        actual = metrics({row['id']: row[field] for row in rows}, labels)
        for key, value in actual.items():
            assert abs(value - rerank['methods'][method]['metrics'][key]) < 1e-12
    output = {'status': 'passed', 'audits': [
        '300 fresh/reopened ID and score lists compared by a second implementation',
        'Production projection and lexical optimization preserve all300 lists',
        'Historical production source archive matches original recorded hashes',
        'All6 systems cover all1271 public queries,100 unique eligible document IDs each',
        'All18 cross-domain aggregate metric triples recomputed by a second implementation with linear gains',
        'No query/document ID self matches in public runs',
        'All12 document/query vector arrays match recorded hashes,dimensions,dtype and finite unit norms',
        'Frozen temporal fixture hashes, split sizes, and scenario-family separation verified',
        'Reranker covers all300 unique official queries; full50 candidate pools preserved and metrics recomputed by a second implementation',
    ], 'artifact_sha256': {p.name: digest(p) for p in OUT.glob('*-results.json') if p.name != 'verification-results.json'}}
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,default=OUT)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'.benchmark-data')
    parser.add_argument('--output',type=Path,help='Optional verification receipt; default does not write files.')
    args=parser.parse_args()
    output=verify(args.input_dir,args.data_dir)
    if args.output:
        from benchmarks.provenance import run_provenance
        output['provenance']=run_provenance()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))


if __name__ == '__main__':
    main()
