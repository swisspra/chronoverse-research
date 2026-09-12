"""Low-overhead instrumentation; all wrappers return unmodified production results."""
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse
from collections import defaultdict
from functools import wraps
import json
import os
import time
from benchmarks.scifact import ROOT, download_dataset, digest
from chronoverse.models import QueryRequest
from chronoverse.store import Store
import chronoverse.store as store_module
from chronoverse import semantic
from chronoverse.vector_index import VectorIndex


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    args=parser.parse_args()
    benchmark_run=BenchmarkRun(allow_dirty=args.allow_dirty)
    os.environ['CHRONOVERSE_EMBEDDINGS']='semantic'
    os.environ.setdefault('CHRONOVERSE_MODEL_CACHE',str(ROOT/'.model-cache'))
    _,queries,_,_=download_dataset(ROOT/'.benchmark-data/scifact')
    store=Store(ROOT/'.benchmark-data/index-v2-ledger.sqlite3',seed=False)
    def request(text):
        return QueryRequest(query=text,world='main',plane='report',perspective='scifact',limit=10)
    store.query(request(next(iter(queries.values()))))
    semantic._embed.cache_clear()
    totals=defaultdict(float)
    originals=[]
    def instrument(owner,name,label):
        original=getattr(owner,name)
        @wraps(original)
        def timed(*args,**kwargs):
            start=time.perf_counter()
            try:
                return original(*args,**kwargs)
            finally:
                totals[label]+=time.perf_counter()-start
        originals.append((owner,name,original))
        setattr(owner,name,timed)
    instrument(Store,'_eligible','eligibility_and_projection')
    instrument(store_module,'_tokens','lexical_tokenization')
    instrument(semantic,'_embed','query_embedding')
    instrument(VectorIndex,'score','vector_read_validate_and_cosine')
    rows=[]
    try:
        for qid,text in list(queries.items())[:10]:
            totals.clear()
            start=time.perf_counter()
            result=store.query(request(text))
            wall=time.perf_counter()-start
            row={'query_id':qid,'wall_seconds':wall,**dict(totals),'ids':[r['id'].removeprefix('scifact-') for r in result['results']]}
            row['other_query_work']=wall-sum(totals.values())
            assert row['other_query_work']>=0
            rows.append(row)
    finally:
        for owner,name,original in originals:
            setattr(owner,name,original)
        store.close()
    timings={key:sum(r[key] for r in rows) for key in ('wall_seconds','eligibility_and_projection','lexical_tokenization','query_embedding','vector_read_validate_and_cosine','other_query_work')}
    baseline=json.loads((ROOT/'docs/benchmarks-v2/index-fresh.json').read_text())
    assert all(row['ids']==baseline['per_query'][row['query_id']]['ids'] for row in rows)
    output={'queries':len(rows),'timing_totals':timings,'vector_fraction':timings['vector_read_validate_and_cosine']/timings['wall_seconds'],'timing_means':{key:value/len(rows) for key,value in timings.items()},'per_query':rows,'notes':['Same original production functions with perf_counter wrappers only; no scoring/eligibility replacement.','Model and persisted documents warmed; ten distinct queries encoded fresh. Wrapper overhead included; shared machine.','Stage totals are disjoint; vector stage includes all SQLite vector reads, checksum validation, reconstruction and cosine. This fraction is an upper bound on what eliminating that entire stage could save in this sample.','All ten instrumented top10 lists checked against the full production benchmark.'],'production_source_sha256':{name:digest(ROOT/'backend/chronoverse'/name) for name in ('store.py','semantic.py','vector_index.py')}}
    benchmark_run.write_json(ROOT/'docs/benchmarks-v2/index-stage-timing.json', output)
    print(json.dumps({'timing_means':output['timing_means'],'vector_fraction':output['vector_fraction']}))

if __name__=='__main__':
    main()
