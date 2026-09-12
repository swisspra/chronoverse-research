"""Deterministic compression and compact summaries; preserve measurement bytes."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from benchmarks.provenance import BenchmarkRun, add_provenance_argument, sha256


def package(run,result_path,contexts_path,output_dir):
    originals={Path(result_path):Path(result_path).read_bytes(),Path(contexts_path):Path(contexts_path).read_bytes()}
    result=json.loads(originals[Path(result_path)])
    if result['status']!='complete':raise ValueError('Only complete delivery measurements can be packaged')
    artifacts={}
    for source,name in [(Path(result_path),'results.json'),(Path(contexts_path),'retrieval-contexts.json')]:
        raw=originals[source];expected=hashlib.sha256(raw).hexdigest()
        compressed=gzip.compress(raw,compresslevel=9,mtime=0)
        if gzip.decompress(compressed)!=raw:raise ValueError('Compression round trip failed')
        if sha256(source)!=expected:raise RuntimeError('Source artifact changed during packaging')
        receipt=run.write_bytes(output_dir/(name+'.gz'),compressed)
        artifacts[name]={'path':name+'.gz','gzip_sha256':receipt['sha256'],'uncompressed_sha256':expected,
                         'uncompressed_bytes':len(raw),'compressed_bytes':len(compressed),
                         'format':'Exact UTF-8 JSON compressed with deterministic gzip mtime=0',
                         'packaging_provenance':receipt['provenance']}
    for source,raw in originals.items():
        if source.read_bytes()!=raw:raise RuntimeError('Source artifact changed during packaging')
    summary={k:v for k,v in result.items() if k not in ('methods','query_manifest','provenance')}
    summary.update(methods={name:{k:v for k,v in method.items() if k!='per_query'} for name,method in result['methods'].items()},
                   split_counts=dict(Counter(q.get('split','unspecified') for q in result['query_manifest'])),
                   original_result_provenance=result['provenance'],raw_artifacts=artifacts)
    return run.write_json(output_dir/'summary.json',summary)


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--contexts',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    run=BenchmarkRun(allow_dirty=args.allow_dirty,sources=[Path(__file__),Path(__file__).with_name('provenance.py')])
    summary=package(run,args.results,args.contexts,args.output_dir)
    print(json.dumps({'status':summary['status'],'output_dir':str(args.output_dir),
                      'artifacts':{name:{k:row[k] for k in ('compressed_bytes','uncompressed_bytes','uncompressed_sha256')} for name,row in summary['raw_artifacts'].items()}}))


if __name__=='__main__':main()
