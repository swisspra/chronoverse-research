"""Offline full500 contexts: frozen pilot ranks plus local remaining queries.

Streams exact JSONL bytes into deterministic gzip chunks. Never calls a provider.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import gzip
import hashlib
import io
import json
from pathlib import Path

from benchmarks.answer_contexts import ROOT,build_manifests,candidate_inventory,load,pilot_queries,query_input,rank_candidates
from benchmarks.answer_experiment import PROMPT,render_prompt
from benchmarks.provenance import BenchmarkRun,add_provenance_argument,sha256


class ChunkWriter:
    def __init__(self,run,directory,max_raw_bytes=64*1024**2):
        self.run=run;self.directory=directory;self.limit=max_raw_bytes
        self.sha=hashlib.sha256();self.bytes=0;self.rows=0;self.chunks=[];self.buffer=None

    def append(self,line):
        if len(line)>self.limit:raise ValueError('A single JSONL row exceeds the fixed chunk limit.')
        if self.buffer is not None and self.chunk_bytes+len(line)>self.limit:self.flush()
        if self.buffer is None:
            self.buffer=io.BytesIO();self.compressor=gzip.GzipFile(filename='',mode='wb',fileobj=self.buffer,mtime=0)
            self.chunk_sha=hashlib.sha256();self.chunk_bytes=0;self.chunk_rows=0
        self.compressor.write(line);self.chunk_sha.update(line);self.chunk_bytes+=len(line);self.chunk_rows+=1
        self.sha.update(line);self.bytes+=len(line);self.rows+=1

    def flush(self):
        if self.buffer is None:return
        self.compressor.close();encoded=self.buffer.getvalue()
        if len(encoded)>=90*1024**2:raise ValueError('Compressed artifact exceeds the conservative90MiB storage limit.')
        filename=f'part-{len(self.chunks)+1:04d}.jsonl.gz';receipt=self.run.write_bytes(self.directory/filename,encoded)
        self.chunks.append({'file':filename,'rows':self.chunk_rows,'raw_bytes':self.chunk_bytes,'raw_sha256':self.chunk_sha.hexdigest(),
            'compressed_bytes':len(encoded),'compressed_sha256':hashlib.sha256(encoded).hexdigest(),'write_provenance':receipt['provenance']})
        self.buffer.close();self.buffer=None

    def finish(self):
        self.flush()
        return {'format':'Concatenate the decompressed chunks in listed order to recover exact JSONL bytes. Each gzip uses empty filename and mtime0.',
            'manifest_sha256':self.sha.hexdigest(),'raw_bytes':self.bytes,'row_count':self.rows,'chunks':self.chunks}


def frozen_pilot(pilot_path,prior):
    opener=gzip.open if pilot_path.suffix=='.gz' else open
    digest=hashlib.sha256();rows={}
    with opener(pilot_path,'rb') as handle:
        for line in handle:
            digest.update(line);row=json.loads(line);key=(row['query_id'],row['arm'])
            if key in rows:raise ValueError('Duplicate frozen pilot row.')
            rows[key]=hashlib.sha256(line).hexdigest()
    if digest.hexdigest()!=prior['manifest_sha256']:raise ValueError('Pilot exact raw manifest hash mismatch.')
    expected={(id,arm) for id in prior['selected_query_ids'] for arm in 'ABCDE'}
    if len(prior['selected_query_ids'])!=50 or set(rows)!=expected:raise ValueError('Expected all50 pilot questions and all5 arms.')
    return rows


def reuse_pilot(queries,prior,units,rank_new):
    chosen={q['id'] for q in queries};old=prior['selected_query_ids']
    if not set(old)<=chosen or len(set(old))!=len(old):raise ValueError('Frozen pilot is not a distinct subset of the full test selection.')
    remaining=[q for q in queries if q['id'] not in set(old)]
    pools,reranked=rank_new(units,[query_input(q) for q in remaining])
    if set(pools)!={q['id'] for q in remaining} or set(reranked)!=set(pools):raise ValueError('New local ranking query coverage mismatch.')
    for qid in old:
        pools[qid]=prior['trace'][qid]['dense_top50'];reranked[qid]=prior['trace'][qid]['cross_encoder_top50']
    return pools,reranked,remaining


def estimates(bounds,queries):
    requests=queries*5*3;caps={arm:16384 if arm=='B' else 8192 for arm in 'ABCDE'}
    return {'status':'Offline future preparation only; no provider calls or full500 dispatch authorized here.',
        'queries':queries,'requests':requests,'repeats':3,'input_token_reservation':sum(sum(v) for v in bounds.values())*3,
        'counting':'UTF8 bytes +512 framing allowance per request; conservative bound, not provider tokenizer count',
        'input_caps':caps,'maximum_bound_by_arm':{a:max(v) for a,v in bounds.items()},
        'rows_exceeding_frozen_input_caps':{a:sum(value>caps[a] for value in values) for a,values in bounds.items()},
        'completion_options':[{'max_completion_tokens':cap,'output_token_reservation':requests*cap,
            'label':'Existing pilot completion cap, unchanged' if cap==1024 else 'Separate future4096 option; motivated by observed transport length flags, not adopted in the live pilot'} for cap in (1024,4096)],
        'usd':None,'pricing':'Future provider pricing not estimated; no paid dispatch.'}


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    parser.add_argument('--fixture',type=Path,default=ROOT/'benchmarks/data/delivery-v3.json.gz')
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--pilot-manifest',type=Path,default=ROOT/'docs/benchmarks-next/answer-contexts-50.manifest.json')
    parser.add_argument('--pilot-rows',type=Path,default=ROOT/'docs/benchmarks-next/answer-contexts-50.jsonl.gz')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'docs/benchmarks-next/answer-full500')
    args=parser.parse_args();run=BenchmarkRun(allow_dirty=args.allow_dirty)
    paths=(args.fixture,args.results,args.pilot_manifest,args.pilot_rows,PROMPT)
    inputs={p:sha256(p) for p in paths};prior=load(args.pilot_manifest);fixture=load(args.fixture);result=load(args.results)
    if prior['fixture_sha256']!=inputs[args.fixture] or prior['retrieval_result_sha256']!=inputs[args.results] or prior['prompt_sha256']!=inputs[PROMPT]:raise ValueError('Frozen pilot fixture/result/prompt input hashes differ.')
    if result['status']!='complete' or result['fixture_sha256']!=inputs[args.fixture]:raise ValueError('Completed frozen retrieval/fixture required.')
    models={p:sha256(p) for folder in ('models--sentence-transformers--all-MiniLM-L6-v2','models--cross-encoder--ms-marco-MiniLM-L6-v2')
        for p in (ROOT/'.model-cache/mps'/folder/'snapshots').rglob('*') if p.is_file()}
    if {str(p.relative_to(ROOT/'.model-cache/mps')):h for p,h in models.items()}!=prior['model_artifact_sha256']:raise ValueError('Model artifact revision differs from frozen pilot.')
    pilot_hashes=frozen_pilot(args.pilot_rows,prior);queries=pilot_queries(fixture['queries'],500);recorded={q['id']:q for q in result['query_manifest']}
    if any(recorded.get(q['id'])!=q for q in queries):raise ValueError('Full query metadata differs from actual frozen retrieval.')
    units=candidate_inventory(fixture)
    pools,reranked,remaining=reuse_pilot(queries,prior,units,lambda u,q:rank_candidates(u,q,ROOT/'.model-cache/mps'))
    print(json.dumps({'stage':'local_ranks_ready','reused_pilot_queries':50,'locally_ranked_queries':len(remaining)}),flush=True)
    writer=ChunkWriter(run,args.output_dir);trace={};bounds=defaultdict(list);matched=0;template=PROMPT.read_text()
    for start in range(0,500,10):
        rows,part_trace=build_manifests(fixture,result,queries[start:start+10],pools,reranked);trace.update(part_trace)
        for row in rows:
            line=(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n').encode();key=(row['query_id'],row['arm'])
            if key in pilot_hashes:
                if hashlib.sha256(line).hexdigest()!=pilot_hashes[key]:raise ValueError('Full preparation would alter a frozen pilot row.')
                matched+=1
            bounds[row['arm']].append(len(render_prompt(row,template).encode())+512);writer.append(line)
    if matched!=250:raise ValueError('Not all frozen pilot rows were preserved.')
    if any(sha256(p)!=value for p,value in {**inputs,**models}.items()):raise RuntimeError('Frozen source inputs/model artifacts changed.')
    storage=writer.finish();estimate=estimates(bounds,500)
    run.write_json(args.output_dir/'manifest.json',{'status':'offline prepared; no hosted inference','query_count':500,'row_count':2500,
        'selected_query_ids':[q['id'] for q in queries],'selected_families':dict(Counter(q['family'] for q in queries)),
        'fixture_sha256':inputs[args.fixture],'retrieval_result_sha256':inputs[args.results],'prompt_sha256':inputs[PROMPT],
        'pilot_manifest_sha256':inputs[args.pilot_manifest],'pilot_raw_manifest_sha256':prior['manifest_sha256'],
        'pilot_exact_rows_preserved':matched,'reused_pilot_rank_queries':50,'local_new_rank_queries':len(remaining),
        'models':prior['models'],'model_artifact_sha256':prior['model_artifact_sha256'],'trace':trace,'storage':storage,'estimate':estimate})
    print(json.dumps({'status':'prepared','queries':500,'rows':2500,'chunks':len(storage['chunks']),'raw_sha256':storage['manifest_sha256'],'estimate':estimate}),flush=True)


if __name__=='__main__':main()
