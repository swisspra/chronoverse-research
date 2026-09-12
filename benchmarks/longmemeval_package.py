"""Lossless LongMemEval context/result publication with separate packaging provenance."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from benchmarks.provenance import BenchmarkRun,add_provenance_argument,sha256


def package(run,result_path,context_path,output_dir):
    result_path,context_path=Path(result_path),Path(context_path)
    original=result_path.read_bytes();contexts=context_path.read_bytes();result=json.loads(original)
    if result['status']!='complete':raise ValueError('Complete retrieval run required')
    if hashlib.sha256(contexts).hexdigest()!=result['contexts_artifact']['sha256']:raise ValueError('Context bytes do not match measured artifact')
    stored={}
    for source,name,raw in [(result_path,'results.json',original),(context_path,'contexts.jsonl',contexts)]:
        expected=hashlib.sha256(raw).hexdigest();encoded=gzip.compress(raw,compresslevel=9,mtime=0)
        if gzip.decompress(encoded)!=raw or sha256(source)!=expected:raise RuntimeError('Source bytes changed during packaging')
        receipt=run.write_bytes(output_dir/(name+'.gz'),encoded)
        stored[name]={'path':name+'.gz','uncompressed_sha256':expected,'uncompressed_bytes':len(raw),
            'gzip_sha256':receipt['sha256'],'compressed_bytes':len(encoded),'gzip_mtime':0,'packaging_provenance':receipt['provenance']}
    if result_path.read_bytes()!=original or context_path.read_bytes()!=contexts:raise RuntimeError('Source artifacts changed')
    summary={k:v for k,v in result.items() if k not in ('per_query','provenance')}
    summary.update(original_result_provenance=result['provenance'],stored_artifacts=stored)
    return run.write_json(output_dir/'summary.json',summary)


def main():
    p=add_provenance_argument(argparse.ArgumentParser());p.add_argument('--results',type=Path,required=True);p.add_argument('--contexts',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args();run=BenchmarkRun(allow_dirty=args.allow_dirty,sources=[Path(__file__),Path(__file__).with_name('provenance.py')])
    result=package(run,args.results,args.contexts,args.output_dir)
    print(json.dumps({'status':result['status'],'files':{name:{k:row[k] for k in ['compressed_bytes','uncompressed_bytes']} for name,row in result['stored_artifacts'].items()}}))


if __name__=='__main__':main()
