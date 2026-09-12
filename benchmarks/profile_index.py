"""Diagnostic cProfile of actual Store queries over the retained SciFact index."""
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse
import cProfile
import json
import os
from pathlib import Path
import pstats
import time
from benchmarks.scifact import ROOT, digest, download_dataset
from chronoverse.models import QueryRequest
from chronoverse.store import Store


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    args=parser.parse_args()
    benchmark_run=BenchmarkRun(allow_dirty=args.allow_dirty)
    os.environ['CHRONOVERSE_EMBEDDINGS']='semantic'
    os.environ.setdefault('CHRONOVERSE_MODEL_CACHE',str(ROOT/'.model-cache'))
    from chronoverse import semantic
    _,queries,_,_=download_dataset(ROOT/'.benchmark-data/scifact')
    store=Store(ROOT/'.benchmark-data/index-v2-ledger.sqlite3',seed=False)
    def run(text):
        return store.query(QueryRequest(query=text,world='main',plane='report',perspective='scifact',limit=10))
    run(next(iter(queries.values())))
    semantic._embed.cache_clear()
    profile=cProfile.Profile()
    start=time.perf_counter()
    for text in list(queries.values())[:5]:
        profile.runcall(run,text)
    elapsed=time.perf_counter()-start
    stats=pstats.Stats(profile)
    rows=[]
    for (filename,line,function),(primitive,calls,self_seconds,cumulative_seconds,_) in stats.stats.items():
        rows.append({'file':filename,'line':line,'function':function,'calls':calls,'self_seconds':self_seconds,'cumulative_seconds':cumulative_seconds})
    rows.sort(key=lambda row:-row['cumulative_seconds'])
    output={'queries':5,'wall_seconds_under_profiler':elapsed,'note':'First five test queries selected without labels. Warm persisted documents/model; fresh query embeddings; cProfile adds overhead, so use attribution rather than capacity estimates. Nested cumulative times overlap.','rows':rows[:60],'production_source_sha256':{name:digest(ROOT/'backend/chronoverse'/name) for name in ('store.py','semantic.py','vector_index.py')}}
    benchmark_run.write_json(ROOT/'docs/benchmarks-v2/index-profile.json', output)
    for row in rows[:25]:
        print(row)
    store.close()

if __name__=='__main__':
    main()
