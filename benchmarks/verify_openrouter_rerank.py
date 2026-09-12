"""Read-only second implementation: native responses -> ranks, qrel metrics, costs.

Never imports the runner, its response validator or its metric functions. This
checks artifact consistency, not cryptographic provider billing authenticity.
"""
from __future__ import annotations
import argparse
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def require(condition,message):
    if not condition:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def object_hash(value):return sha(json.dumps(value,sort_keys=True,ensure_ascii=False).encode())


def frozen_bytes(repo,commit,path):
    require(bool(re.fullmatch(r'[0-9a-f]{40}',commit)),'Invalid frozen commit identity.')
    return subprocess.check_output(['git','-C',str(repo),'show',commit+':'+path],stderr=subprocess.PIPE)


def independently_score(ranked,judged):
    gains=[(2**judged.get(id,0)-1)/math.log2(position+2) for position,id in enumerate(ranked[:10])]
    ideal=sorted(judged.values(),reverse=True)[:10]
    denominator=sum((2**grade-1)/math.log2(position+2) for position,grade in enumerate(ideal))
    relevant=[position+1 for position,id in enumerate(ranked[:10]) if judged.get(id,0)>0]
    return {'ndcg@10':sum(gains)/denominator if denominator else 0,'recall@10':len(relevant)/len(judged) if judged else 0,
        'mrr@10':1/min(relevant) if relevant else 0,'hit@1':int(1 in relevant)}


def close(actual,expected,label):
    require(isinstance(actual,(int,float)) and math.isfinite(actual) and abs(actual-expected)<=1e-12,label)


def verify(result_path,*,data_dir=ROOT/'.benchmark-data/scifact',original_path=ROOT/'docs/benchmarks-v2/rerank-results.json',repo=ROOT,endpoint='https://openrouter.ai/api/v1/rerank'):
    result_path=Path(result_path);data_dir=Path(data_dir);original_path=Path(original_path)
    raw=result_path.read_bytes();result=json.loads(raw);original_raw=original_path.read_bytes();original=json.loads(original_raw)
    require(result['status']=='complete','Expected complete result, not a selected successful subset.')
    commit=result['provenance']['git_commit'];recorded_hashes=result['input_files_sha256']
    expected_files={'docs/benchmarks-v2/rerank-results.json':original_raw,
        '.benchmark-data/scifact/canonical-records.jsonl':(data_dir/'canonical-records.jsonl').read_bytes(),
        '.benchmark-data/scifact/queries.jsonl':(data_dir/'queries.jsonl').read_bytes(),
        '.benchmark-data/scifact/qrels/test.tsv':(data_dir/'qrels/test.tsv').read_bytes()}
    for source in ('benchmarks/openrouter_rerank.py','docs/benchmarks-next/OPENROUTER-RERANK-PROTOCOL.md'):
        expected_files[source]=frozen_bytes(repo,commit,source)
    require(set(recorded_hashes)==set(expected_files),'Frozen input/source hash key set differs.')
    for name,content in expected_files.items():require(recorded_hashes[name]==sha(content),'Frozen source/input SHA mismatch: '+name)
    require(original_raw==frozen_bytes(repo,commit,'docs/benchmarks-v2/rerank-results.json'),'Original pool artifact differs from frozen commit.')
    for path,key in (('canonical-records.jsonl',None),('queries.jsonl','queries.jsonl'),('qrels/test.tsv','qrels/test.tsv')):
        expected=original['parameters']['canonical_sha256'] if key is None else original['dataset_hashes'][key]
        require(sha((data_dir/path).read_bytes())==expected,'Canonical/official data does not match historical benchmark.')
    documents={}
    for line in (data_dir/'canonical-records.jsonl').read_text().splitlines():
        row=json.loads(line);require(row['doc_id'] not in documents,'Duplicate canonical document.');documents[row['doc_id']]=row['text']
    queries={row['_id']:row['text'] for row in map(json.loads,(data_dir/'queries.jsonl').read_text().splitlines())};qrels={}
    with (data_dir/'qrels/test.tsv').open() as handle:
        for row in csv.DictReader(handle,delimiter='\t'):
            if int(row['score'])>0:qrels.setdefault(row['query-id'],{})[row['corpus-id']]=int(row['score'])
    source={row['id']:row for row in original['per_query']};native={}
    require(len(documents)==5183 and len(qrels)==len(source)==len(original['per_query'])==300,'Official full test inventory mismatch.')
    require(set(source)==set(qrels) and len(result['requests'])==300,'Scored query set mismatch.')
    require(result['parameters']['requested_model']=='cohere/rerank-v3.5' and result['parameters']['actual_model']=='rerank-v3.5','Model parameter mismatch.')
    costs=[];seconds=[];known_units=[];all_requests=[]
    for request_id,row in result['requests'].items():
        qid=row['query_id'];require(qid in source and qid not in native,'Duplicate/unexpected native query.');old=source[qid]
        require(old['query']==queries[qid],'Original query differs from official query.')
        candidates=old['candidates']
        require(len(candidates)==len(set(candidates))==50 and set(candidates)<=documents.keys(),'Invalid frozen candidate pool.')
        require(len(old['reranked'])==50 and set(old['reranked'])==set(candidates),'Historical CE is not a pool permutation.')
        require(row['status']=='complete' and row['candidates']==candidates,'Incomplete request or frozen pool/order mismatch.')
        body={'model':'cohere/rerank-v3.5','query':queries[qid],'documents':[documents[id] for id in candidates],'top_n':50}
        request={'query_id':qid,'candidates':candidates,'body':body};all_requests.append(request)
        require(row['input_sha256']==object_hash(body),'Exact request body hash mismatch.')
        require(request_id==object_hash({'endpoint':endpoint,**request}),'Endpoint-bound request ID mismatch.')
        response=row['response'];require(response.get('model')=='rerank-v3.5','Native response identity mismatch.')
        require(isinstance(response.get('results'),list) and len(response['results'])==50,'Missing native response indices.')
        scores={}
        for entry in response['results']:
            index=entry.get('index');score=entry.get('relevance_score')
            require(type(index) is int and 0<=index<50 and index not in scores,'Duplicate/out-of-range native index.')
            require(type(score) in (int,float) and math.isfinite(score),'Nonfinite native relevance score.')
            scores[index]=float(score)
        ranked=[candidates[i] for i in sorted(range(50),key=lambda i:(-scores[i],candidates[i]))]
        require(row['ranked_ids']==ranked,'Saved rank differs from raw native scores.')
        require(row['scores']=={candidates[i]:scores[i] for i in range(50)},'Saved score map differs from native indices.')
        usage=response.get('usage');require(isinstance(usage,dict) and 'cost' in usage,'Missing observed native cost.')
        cost=Decimal(str(usage['cost']));require(cost.is_finite() and 0<=cost<=Decimal('.01'),'Invalid/over-reservation native cost.')
        require(Decimal(row['cost_usd'])==cost and Decimal(row['reserved_usd'])==Decimal('.01'),'Saved cost/reservation mismatch.');costs.append(cost)
        elapsed=row['seconds'];require(type(elapsed) in (int,float) and math.isfinite(elapsed) and elapsed>=0,'Invalid native latency.');seconds.append(elapsed)
        if isinstance(usage.get('search_units'),(int,float)) and math.isfinite(usage['search_units']):known_units.append(usage['search_units'])
        native[qid]=ranked
    all_requests.sort(key=lambda r:int(r['query_id']))
    require(result['estimate']['input_sha256']==object_hash(all_requests),'Whole request inventory hash mismatch.')
    require(result['estimate']['requests']==300 and result['estimate']['documents_per_request']==50,'Planned inventory mismatch.')
    require(Decimal(result['estimate']['total_reservation_usd'])==Decimal(3) and sum(costs)<=Decimal(3),'Whole-run budget mismatch.')
    require(Decimal(result['observed_cost_usd'])==sum(costs),'Observed cost total mismatch.')
    require(result['observed_search_units']==(sum(known_units) if known_units else None) and result['responses_without_search_units']==300-len(known_units),'Search-unit accounting mismatch.')
    for metric,expected in (('mean_seconds',np.mean(seconds)),('p50_seconds',np.percentile(seconds,50)),('p95_seconds',np.percentile(seconds,95))):close(result['hosted_rerank_only_latency'][metric],float(expected),'Latency aggregate mismatch.')
    per_query={row['id']:row for row in result['per_query']};require(len(per_query)==len(result['per_query'])==300 and set(per_query)==set(source),'Per-query report coverage mismatch.')
    measured={name:{} for name in ('rrf_minilm_top50','rrf_minilm_cross_encoder','cohere_rerank_v3_5')}
    for qid,old in source.items():
        row=per_query[qid]
        require(row['query']==queries[qid] and row['candidates']==old['candidates'] and row['local_ce_ids']==old['reranked'] and row['cohere_ids']==native[qid],'Per-query report ranking/text mismatch.')
        for name,ranking in (('rrf_minilm_top50',old['candidates']),('rrf_minilm_cross_encoder',old['reranked']),('cohere_rerank_v3_5',native[qid])):
            measured[name][qid]=independently_score(ranking,qrels[qid])
            for metric,value in measured[name][qid].items():close(row['metrics'][name][metric],value,'Per-query metric mismatch.')
    for name,values in measured.items():
        for metric in next(iter(values.values())):
            expected=float(np.mean([v[metric] for v in values.values()]));close(result['methods'][name][metric],expected,'Aggregate qrel metric mismatch.')
            if name in original['methods']:close(original['methods'][name]['metrics'][metric],expected,'Historical metric reproduction mismatch.')
    raw_p={}
    for baseline in ('rrf_minilm_top50','rrf_minilm_cross_encoder'):
        d=np.array([measured['cohere_rerank_v3_5'][r['id']]['ndcg@10']-measured[baseline][r['id']]['ndcg@10'] for r in original['per_query']]);rng=np.random.default_rng(20260913)
        boot=d[rng.integers(0,300,size=(10000,300))].mean(axis=1);permuted=(rng.choice((-1,1),size=(20000,300))*d).mean(axis=1)
        observed=result['paired_ndcg_contrasts'][baseline];require(observed['query_pairs']==300 and observed['seed']==20260913,'Paired unit/seed mismatch.')
        close(observed['ndcg_difference'],float(d.mean()),'Paired effect mismatch.')
        for field,quantiles in (('ci95',[.025,.975]),('bonferroni_ci97_5',[.0125,.9875])):
            for actual,expected in zip(observed[field],np.quantile(boot,quantiles),strict=True):close(actual,float(expected),'Paired interval mismatch.')
        raw_p[baseline]=float((1+np.count_nonzero(np.abs(permuted)>=abs(d.mean())-1e-12))/20001);close(observed['p_raw'],raw_p[baseline],'Paired p-value mismatch.')
    adjusted=0
    for index,(name,p) in enumerate(sorted(raw_p.items(),key=lambda pair:pair[1])):
        adjusted=max(adjusted,min(1,(2-index)*p));close(result['paired_ndcg_contrasts'][name]['p_holm'],adjusted,'Holm adjustment mismatch.')
    return {'status':'verified','queries':300,'candidate_score_checks':15000,'methods':3,'cost_usd':str(sum(costs)),
        'result_sha256':sha(raw),'frozen_commit':commit,'verifier_sha256':sha(Path(__file__).read_bytes()),
        'scope':'Independent artifact/hash/rank/qrel/statistical/cost consistency; not independent provider billing authentication. No network or data writes.'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('result',type=Path);parser.add_argument('--data-dir',type=Path,default=ROOT/'.benchmark-data/scifact')
    parser.add_argument('--original',type=Path,default=ROOT/'docs/benchmarks-v2/rerank-results.json');parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=verify(args.result,data_dir=args.data_dir,original_path=args.original)
    if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
