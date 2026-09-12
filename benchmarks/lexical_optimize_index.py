"""Bounded lexical postings optimization; reuse persisted vectors, no cold rebuild."""
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse
import json
import os
import platform
import time
from benchmarks.scifact import ROOT, download_dataset, digest, emit
from benchmarks.metrics import aggregate_metrics, latency_summary
from chronoverse.models import QueryRequest
from chronoverse.store import Store


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    args=parser.parse_args()
    benchmark_run=BenchmarkRun(allow_dirty=args.allow_dirty)
    os.environ['CHRONOVERSE_EMBEDDINGS']='semantic'
    os.environ.setdefault('CHRONOVERSE_MODEL_CACHE',str(ROOT/'.model-cache'))
    from chronoverse import semantic
    _,queries,qrels,hashes=download_dataset(ROOT/'.benchmark-data/scifact')
    baseline_path=ROOT/'docs/benchmarks-v2/optimization-results.json'
    baseline=json.loads(baseline_path.read_text())
    assert hashes==baseline['dataset_sha256']
    store=Store(ROOT/'.benchmark-data/index-v2-ledger.sqlite3',seed=False)
    def run(text):
        start=time.perf_counter()
        result=store.query(QueryRequest(query=text,world='main',plane='report',perspective='scifact',limit=10))
        return {'seconds':time.perf_counter()-start,'ids':[r['id'].removeprefix('scifact-') for r in result['results']],'scores':[r['score'] for r in result['results']]}
    before=store._db.execute('SELECT COUNT(*) FROM derived_vectors').fetchone()[0]
    cold=run(next(iter(queries.values())))
    semantic._embed.cache_clear()
    rows={}
    for i,(qid,text) in enumerate(queries.items()):
        rows[qid]=run(text)
        if (i+1)%50==0:
            emit('lexical_optimization',completed=i+1)
    changes=[qid for qid,row in rows.items() if row['ids']!=baseline['per_query'][qid]['ids'] or row['scores']!=baseline['per_query'][qid]['scores']]
    output={'status':'complete','benchmark':'SciFact production bounded lexical token-postings cache','indexed_count':5183,'test_query_count':300,'change':'Store-owned single-cohort unique-token postings,64MiB retained-object cap,exact ordered projected-text fingerprint. Over-budget fallback computes original overlap. No model, threshold, graph, ranking or answer cache changes.','baseline_sha256':digest(baseline_path),'dataset_sha256':hashes,'canonical_text_sha256':baseline['canonical_text_sha256'],'cold_reopened_query':cold,'vector_rows_before':before,'vector_rows_after':store._db.execute('SELECT COUNT(*) FROM derived_vectors').fetchone()[0],'warm_latency':latency_summary([r['seconds'] for r in rows.values()]),'metrics':aggregate_metrics({qid:r['ids'] for qid,r in rows.items()},qrels),'preservation':{'compared_queries':300,'identical_ids_and_scores':300-len(changes),'changed_query_ids':changes},'query_embedding_cache':semantic._embed.cache_info()._asdict(),'lexical_index':store._lexical_index.statistics(),'per_query':rows,'production_source_sha256':{name:digest(ROOT/'backend/chronoverse'/name) for name in ('store.py','semantic.py','vector_index.py','lexical_index.py','models.py')},'runner_sha256':digest(__file__),'environment':{'python':platform.python_version(),'platform':platform.platform()},'limitations':['Retained persisted index reused; no cold document encoding rerun.','Warm model, fresh query encoding each unique query after cold pilot; no query cache hits expected.','Shared-machine historical before/after timing; changing CPU contention prevents attributing all observed difference to this code change.','Public document retrieval with no lifecycle events in SciFact; separate temporal regression tests verify the event projection semantics.']}
    store.close()
    path=ROOT/'docs/benchmarks-v2/lexical-optimization-results.json'
    benchmark_run.write_json(path, output)
    emit('complete',output=str(path),preservation=output['preservation'],latency=output['warm_latency'])

if __name__=='__main__':
    main()
