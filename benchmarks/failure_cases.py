"""Select deterministic illustrative wins/losses without changing aggregate results."""
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse
import json
from pathlib import Path


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    args=parser.parse_args()
    benchmark_run=BenchmarkRun(allow_dirty=args.allow_dirty)
    out = Path('docs/benchmarks')
    public = Path('.benchmark-data/scifact')
    results = json.loads((out/'scifact-results.json').read_text())
    queries = {row['_id']:row['text'] for row in map(json.loads,(public/'queries.jsonl').read_text().splitlines())}
    corpus = {row['_id']:row for row in map(json.loads,(public/'corpus.jsonl').read_text().splitlines())}
    names = ('bm25','dense_minilm','rrf_bm25_dense','chronoverse_store_optimized_cache')
    # Each run file contains the original ranked document IDs.
    runs = {name:json.loads((out/f'scifact-{name}.run.json').read_text()) for name in names}
    runs = {name:value.get('rankings',value) for name,value in runs.items()}
    chrono='chronoverse_store_optimized_cache'
    hybrid='rrf_bm25_dense'
    delta = lambda row:row['metrics'][chrono]['ndcg@10']-row['metrics'][hybrid]['ndcg@10']
    selected=[]
    for label, ordered in [('largest losses versus hybrid',sorted(results['per_query'],key=lambda r:(delta(r),int(r['query_id'])))),
                           ('largest gains versus hybrid',sorted(results['per_query'],key=lambda r:(-delta(r),int(r['query_id']))))]:
        for row in ordered[:2]:
            qid=row['query_id']
            selected.append(dict(selection=label,query_id=qid,query=queries[qid],metrics=row['metrics'],
                rankings={name:[dict(id=aid,title=corpus[aid]['title']) for aid in runs[name][qid]] for name in names}))
    fixture=json.loads(Path('benchmarks/data/temporal-v1.json').read_text())
    temporal=json.loads((out/'temporal-results.json').read_text())
    by_id={a['id']:a for a in fixture['assertions']}
    query=next(q for q in sorted(fixture['queries'],key=lambda q:q['id']) if q['category']=='retraction_empty')
    retrieved=temporal['systems']['Chronoverse stock']['rankings'][query['id']]
    empty_case={**query,'returned':[dict(id=aid,subject=by_id[aid]['subject'],predicate=by_id[aid]['predicate'],object=by_id[aid]['object']) for aid in retrieved]}
    benchmark_run.write_json(out/'failure-cases.json', dict(selection_note='Deterministic largest positive/negative nDCG differences; illustrative only, all test queries remain in aggregate scores.',scifact=selected,temporal_empty=empty_case))


if __name__=='__main__':
    main()
