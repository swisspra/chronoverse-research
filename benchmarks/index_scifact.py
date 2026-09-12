"""Benchmark actual persistent-index Store without monkeypatching any backend code."""
from __future__ import annotations
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time

from benchmarks.scifact import ROOT, canonical_assertion, digest, download_dataset, emit
from benchmarks.metrics import aggregate_metrics, latency_summary
from chronoverse.models import QueryRequest
from chronoverse.store import Store, _text


def query(store, text):
    start = time.perf_counter()
    result = store.query(QueryRequest(query=text, world='main', plane='report', perspective='scifact', limit=10))
    return {'seconds': time.perf_counter()-start,
            'ids': [row['id'].removeprefix('scifact-') for row in result['results']],
            'scores': [row['score'] for row in result['results']]}


def count_vectors(path):
    with sqlite3.connect(path) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='derived_vectors'").fetchone():
            return 0
        return db.execute('SELECT COUNT(*) FROM derived_vectors').fetchone()[0]


def worker(args, benchmark_run):
    from chronoverse import semantic
    corpus, queries, qrels, hashes = download_dataset(ROOT / '.benchmark-data/scifact')
    start = time.perf_counter()
    store = Store(args.db, seed=False)
    ledger_seconds = 0
    if args.phase == 'fresh':
        records = [canonical_assertion(row) for row in corpus]
        clock = time.perf_counter()
        for offset in range(0, len(records), 500):
            store.add_assertions_atomic(records[offset:offset+500])
        ledger_seconds = time.perf_counter()-clock
    canonical = [_text(store.get_assertion('scifact-'+row['_id'])) for row in corpus]
    canonical_hash = hashlib.sha256('\n'.join(canonical).encode()).hexdigest()
    before = count_vectors(args.db)
    first_id, first_text = next(iter(queries.items()))
    cold = query(store, first_text)
    after = count_vectors(args.db)
    emit('index_cold_query', phase=args.phase, seconds=cold['seconds'], vectors_before=before, vectors_after=after)
    # Clear only the legacy query-embedding LRU, not persisted documents or answers.
    # Every measured unique query below therefore includes fresh query inference.
    semantic._embed.cache_clear()
    rows = {}
    for i, (qid, text) in enumerate(queries.items()):
        rows[qid] = query(store, text)
        if (i+1) % 50 == 0:
            emit('query_progress', phase=args.phase, completed=i+1)
    run = {qid: row['ids'] for qid,row in rows.items()}
    result = {'phase': args.phase, 'indexed_count':len(corpus),'test_query_count':len(queries),
              'dataset_sha256':hashes,'canonical_text_sha256':canonical_hash,
              'ledger_index_seconds':ledger_seconds,'cold_first_query':{'query_id':first_id,**cold},
              'vector_rows_before':before,'vector_rows_after_cold':after,
              'metrics':aggregate_metrics(run,qrels), 'warm_latency':latency_summary([row['seconds'] for row in rows.values()]),
              'per_query':rows,'query_embedding_cache':semantic._embed.cache_info()._asdict(),
              'model_identity':semantic.model_identity(),'total_worker_seconds':time.perf_counter()-start}
    store.close()
    result['sqlite_bytes_after_close'] = args.db.stat().st_size
    benchmark_run.write_json(args.output, result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase',choices=['fresh','reopened'])
    parser.add_argument('--db',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/benchmarks-v2/index-results.json')
    add_provenance_argument(parser)
    args = parser.parse_args()
    benchmark_run = BenchmarkRun(allow_dirty=args.allow_dirty)
    os.environ['CHRONOVERSE_EMBEDDINGS']='semantic'
    os.environ.setdefault('CHRONOVERSE_MODEL_CACHE',str(ROOT/'.model-cache'))
    if args.phase:
        return worker(args, benchmark_run)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    baseline_path=ROOT/'docs/benchmarks/scifact-results.json'
    baseline=json.loads(baseline_path.read_text())
    v1run=json.loads((ROOT/'docs/benchmarks/scifact-chronoverse_store_optimized_cache.run.json').read_text())
    v1run=v1run.get('rankings',v1run)
    pilot=json.loads((ROOT/'docs/benchmarks/scifact-stock-pilot.json').read_text())
    with tempfile.TemporaryDirectory(prefix='index-v2-',dir=ROOT/'.benchmark-data') as temporary:
        db=Path(temporary)/'ledger.sqlite3'
        phases={}
        for phase in ('fresh','reopened'):
            output=Path(temporary)/('index-'+phase+'.json')
            subprocess.run([sys.executable,'-m','benchmarks.index_scifact','--phase',phase,'--db',str(db),'--output',str(output), *(['--allow-dirty'] if args.allow_dirty else [])],check=True)
            phases[phase]=json.loads(output.read_text())
    for phase, data in phases.items():
        benchmark_run.write_json(args.output.with_name('index-'+phase+'.json'), {**data, 'worker_provenance':data.get('provenance')})
    fresh,reopened=phases['fresh'],phases['reopened']
    assert fresh['canonical_text_sha256']==baseline['canonical_text_sha256']
    assert fresh['dataset_sha256']==baseline['sha256']
    changed=[qid for qid,row in fresh['per_query'].items() if row['ids']!=v1run[qid]]
    differences=[{'query_id':qid,'v1':v1run[qid],'v2':fresh['per_query'][qid]['ids']} for qid in changed]
    reopen_changed=[qid for qid,row in reopened['per_query'].items() if row['ids']!=fresh['per_query'][qid]['ids'] or row['scores']!=fresh['per_query'][qid]['scores']]
    score_comparisons=[{'query_id':row['query_id'],'same_ids':fresh['per_query'][row['query_id']]['ids']==row['ranked_ids'],'same_rounded_scores':fresh['per_query'][row['query_id']]['scores']==row['ranked_scores']} for row in pilot['rows']]
    output={'benchmark':'SciFact production persistent vector index v2','created_at':datetime.now(timezone.utc).isoformat(),'status':'complete',
            'indexed_count':5183,'test_query_count':300,'canonical_text_sha256':fresh['canonical_text_sha256'],
            'dataset_sha256':fresh['dataset_sha256'],'v1_results_sha256':digest(baseline_path),
            'entrypoint':'Unmodified chronoverse.store.Store.query, semantic mode; no benchmark cache replacement',
            'index':{'storage':'Per-profile derived_vectors SQLite table','key':'SHA256 loaded model artifacts/preprocessor identity + SHA256 exact eligible projected canonical text','dimensions':384,'storage_dtype':'little-endian float64','document_storage_batch':32,'model_inference_batch':4,'cosine_chunk':256,'approximate_search':False,'answer_cache':False},
            'timing_protocol':'Each phase runs in a new Python process. Cold first query includes model initialization/fingerprinting and (fresh phase only) lazy document indexing. Warm300 includes fresh query inference for every query: query LRU cleared after cold pilot, unique queries; document vectors persisted. OS page cache is uncontrolled; reopened means process-cold/model-cold, not disk-cold. No competing baseline rerun, old timing is historical.',
            'phases':phases,'preservation':{'compared_queries':300,'identical_top10_ids':300-len(changed),'ranking_changes':differences,'v1_stock_pilot_score_comparisons':score_comparisons,'reopened_identical_ids_and_scores':300-len(reopen_changed),'reopened_changes':reopen_changed,'score_comparison_limit':'v1 full300 artifacts retained IDs only; exact rounded-score equality can only be checked for two saved stock pilot queries.'},
            'v1_comparison':{'stock_pilot':baseline['stock_pilot'],'benchmark_only_cache_latency':baseline['methods']['chronoverse_store_optimized_cache']['warm_latency'],'metrics':baseline['methods']['chronoverse_store_optimized_cache']['metrics']},
            'production_source_sha256':{name:digest(ROOT/'backend/chronoverse'/name) for name in ('store.py','semantic.py','vector_index.py','models.py')},
            'runner_sha256':digest(Path(__file__)),
            'environment':{'python':platform.python_version(),'platform':platform.platform(),'cpu_count':os.cpu_count(),'versions':{name:version(name) for name in ('fastembed','onnxruntime','numpy')},'onnx_threads':2},
            'limitations':['Same public retrieval test as v1; not temporal reasoning or generative answer evaluation.','Metadata/gates, ranking math, model default and text projection unchanged. Batched ONNX inference/cosine may produce tiny floating-point differences; preservation results are measured, not assumed.','A concurrent local agent may affect latency; not a controlled capacity benchmark.','Vectors are derived per model/text and accumulate on disk; no retention/compaction policy or ANN index is included.']}
    benchmark_run.write_json(args.output, output)
    emit('complete', output=str(args.output),preservation=output['preservation'],fresh_latency=fresh['warm_latency'],reopened_latency=reopened['warm_latency'])

if __name__=='__main__':
    main()
