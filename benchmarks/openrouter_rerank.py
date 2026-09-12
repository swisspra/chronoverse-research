"""Frozen-pool native Cohere rerank comparison; prepare by default, no retries."""
from __future__ import annotations
import argparse
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
import numpy as np
from benchmarks.answer_experiment import atomic_checkpoint,checkpoint_lock
from benchmarks.provenance import BenchmarkRun,add_provenance_argument,sha256

ROOT=Path(__file__).resolve().parents[1]
MODEL='cohere/rerank-v3.5'
ACTUAL_MODEL='rerank-v3.5'
RESERVATION=Decimal('0.01')
SEED=20260913


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def sources(original,canonical,queries_file,qrels_file):
    source=json.loads(original.read_text())
    if sha256(canonical)!=source['parameters']['canonical_sha256']:raise ValueError('Canonical text hash differs from the original reranker input.')
    for path,key in ((queries_file,'queries.jsonl'),(qrels_file,'qrels/test.tsv')):
        if sha256(path)!=source['dataset_hashes'][key]:raise ValueError('Official query/qrel hash differs from original benchmark.')
    documents={}
    for line in canonical.read_text().splitlines():
        row=json.loads(line)
        if row['doc_id'] in documents:raise ValueError('Duplicate canonical document.')
        documents[row['doc_id']]=row['text']
    queries={q['_id']:q['text'] for q in map(json.loads,queries_file.read_text().splitlines())}
    qrels={}
    with qrels_file.open() as handle:
        for row in csv.DictReader(handle,delimiter='\t'):
            if int(row['score'])>0:qrels.setdefault(row['query-id'],{})[row['corpus-id']]=int(row['score'])
    rows=source['per_query']
    if len(documents)!=5183 or len(rows)!=300 or len(qrels)!=300 or {r['id'] for r in rows}!=set(qrels):raise ValueError('Expected exact official 300-query/5183-document SciFact test inventory.')
    for row in rows:
        if row['query']!=queries[row['id']]:raise ValueError('Frozen query text mismatch.')
        for key in ('candidates','reranked'):
            ids=row[key]
            if len(ids)!=50 or len(set(ids))!=50 or not set(ids)<=documents.keys():raise ValueError('Expected 50 distinct canonical candidate IDs.')
        if set(row['candidates'])!=set(row['reranked']):raise ValueError('Historical cross-encoder changed the candidate pool.')
    for name,key in (('rrf_minilm_top50','candidates'),('rrf_minilm_cross_encoder','reranked')):
        recomputed=[metrics(row[key],qrels[row['id']]) for row in rows]
        if any(abs(float(np.mean([r[metric] for r in recomputed]))-source['methods'][name]['metrics'][metric])>1e-12 for metric in recomputed[0]):raise ValueError('Historical metrics fail independent reproduction before dispatch.')
    return source,documents,qrels


def requests_for(source,documents):
    return [{'query_id':row['id'],'candidates':row['candidates'],
        'body':{'model':MODEL,'query':row['query'],'documents':[documents[id] for id in row['candidates']],'top_n':50}}
        for row in sorted(source['per_query'],key=lambda r:int(r['id']))]


def validate_response(response,count):
    if response.get('model')!=ACTUAL_MODEL:raise ValueError('Returned native reranker identity mismatch.')
    rows=response.get('results')
    if not isinstance(rows,list) or len(rows)!=count:raise ValueError('Native rerank must return every candidate index.')
    scores={}
    for row in rows:
        index=row.get('index');score=row.get('relevance_score')
        if type(index) is not int or index not in range(count) or index in scores:raise ValueError('Duplicate/out-of-range rerank index.')
        if type(score) not in (int,float) or not math.isfinite(score):raise ValueError('Rerank scores must be finite numbers.')
        scores[index]=float(score)
    usage=response.get('usage')
    if not isinstance(usage,dict) or 'cost' not in usage:raise ValueError('Missing provider usage.cost; budget cannot be verified.')
    cost=Decimal(str(usage['cost']))
    if not cost.is_finite() or cost<0:raise ValueError('Provider cost must be finite and nonnegative.')
    return scores,cost


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def send(endpoint,key,body,timeout):
    request=Request(endpoint,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    with build_opener(NoRedirect).open(request,timeout=timeout) as response:return json.load(response)


def execute(requests,*,base_url,key,checkpoint,max_usd,input_hashes,guard=lambda:None,transport=send):
    parsed=urlsplit(base_url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Invalid base URL.')
    endpoint=base_url.rstrip('/')+'/rerank';budget=Decimal(str(max_usd))
    if not budget.is_finite() or budget<=0 or budget>3 or RESERVATION*len(requests)>budget:raise ValueError('Whole-run reservation exceeds the explicit budget or $3 ceiling; no dispatch.')
    if not key.strip():raise ValueError('Empty runtime credential.')
    identity=digest({'endpoint':endpoint,'requested_model':MODEL,'expected_model':ACTUAL_MODEL,'requests':requests,'input_hashes':input_hashes,'reservation':str(RESERVATION),'budget':str(budget)})
    with checkpoint_lock(checkpoint):
        state=json.loads(checkpoint.read_text()) if checkpoint.exists() else {'identity':identity,'requests':{},'endpoint':endpoint,'input_hashes':input_hashes,'max_usd':str(budget)}
        if state['identity']!=identity:raise ValueError('Checkpoint endpoint/model/input/budget identity mismatch.')
        expected_ids={digest({'endpoint':endpoint,**r}) for r in requests}
        if not state['requests'].keys()<=expected_ids:raise ValueError('Checkpoint contains an unplanned dispatch ID.')
        if any(r['status']!='complete' for r in state['requests'].values()):raise ValueError('Uncertain or guarded dispatch exists; no automatic retry.')
        for request in requests:
            rid=digest({'endpoint':endpoint,**request})
            if rid in state['requests']:
                cached=state['requests'][rid];scores,cost=validate_response(cached['response'],len(request['candidates']))
                expected=[request['candidates'][i] for i in sorted(scores,key=lambda index:(-scores[index],request['candidates'][index]))]
                if cost>RESERVATION or Decimal(cached['cost_usd'])!=cost or cached['ranked_ids']!=expected:raise ValueError('Cached native response/cost/ranking failed integrity check.')
                continue
            guard()
            result={'query_id':request['query_id'],'candidates':request['candidates'],'input_sha256':digest(request['body']),'reserved_usd':str(RESERVATION),'status':'pending'}
            state['requests'][rid]=result;atomic_checkpoint(checkpoint,state)
            start=time.perf_counter()
            try:response=transport(endpoint,key,request['body'],90)
            except Exception as exc:
                result.update(status='uncertain',seconds=time.perf_counter()-start,error_type=type(exc).__name__,http_status=exc.code if isinstance(exc,HTTPError) else None)
                atomic_checkpoint(checkpoint,state)
                raise RuntimeError('Dispatch outcome uncertain; retained pending charge and no retry.') from None
            result.update(response=response,seconds=time.perf_counter()-start,status='invalid_response');atomic_checkpoint(checkpoint,state)
            try:scores,cost=validate_response(response,len(request['candidates']))
            except Exception as exc:
                result['error_type']=type(exc).__name__;atomic_checkpoint(checkpoint,state)
                raise RuntimeError('Native response/cost validation failed; raw response retained, no retry or chat fallback.') from None
            result['cost_usd']=str(cost)
            spent=sum(Decimal(r.get('cost_usd','0')) for r in state['requests'].values())
            if cost>RESERVATION or spent>budget:
                result['status']='budget_breach';atomic_checkpoint(checkpoint,state)
                raise RuntimeError('Observed charge exceeded reservation; further requests stopped. Existing provider charge cannot be undone.')
            order=sorted(scores,key=lambda index:(-scores[index],request['candidates'][index]))
            result.update(status='complete',ranked_ids=[request['candidates'][i] for i in order],scores={request['candidates'][i]:value for i,value in scores.items()})
            atomic_checkpoint(checkpoint,state)
        return state


def metrics(ranking,gold):
    dcg=sum((2**gold.get(id,0)-1)/math.log2(i+2) for i,id in enumerate(ranking[:10]))
    ideal=sum((2**grade-1)/math.log2(i+2) for i,grade in enumerate(sorted(gold.values(),reverse=True)[:10]))
    hits=[i+1 for i,id in enumerate(ranking[:10]) if gold.get(id,0)>0]
    return {'ndcg@10':dcg/ideal if ideal else 0,'recall@10':len(hits)/len(gold) if gold else 0,'mrr@10':1/hits[0] if hits else 0,'hit@1':int(bool(hits) and hits[0]==1)}


def evaluate(source,qrels,state):
    hosted={r['query_id']:r for r in state['requests'].values()};runs={name:{} for name in ('rrf_minilm_top50','rrf_minilm_cross_encoder','cohere_rerank_v3_5')};per_query=[]
    for row in source['per_query']:
        qid=row['id'];rankings={'rrf_minilm_top50':row['candidates'],'rrf_minilm_cross_encoder':row['reranked'],'cohere_rerank_v3_5':hosted[qid]['ranked_ids']}
        for name,ranking in rankings.items():runs[name][qid]=metrics(ranking,qrels[qid])
        per_query.append({'id':qid,'query':row['query'],'candidates':row['candidates'],'local_ce_ids':row['reranked'],'cohere_ids':hosted[qid]['ranked_ids'],'metrics':{name:runs[name][qid] for name in runs}})
    means={name:{metric:float(np.mean([r[metric] for r in values.values()])) for metric in next(iter(values.values()))} for name,values in runs.items()}
    for name in ('rrf_minilm_top50','rrf_minilm_cross_encoder'):
        if any(abs(value-source['methods'][name]['metrics'][metric])>1e-12 for metric,value in means[name].items()):raise ValueError('Independent metric calculation does not reproduce historical baseline.')
    comparisons={}
    for name in ('rrf_minilm_top50','rrf_minilm_cross_encoder'):
        d=np.array([runs['cohere_rerank_v3_5'][r['id']]['ndcg@10']-runs[name][r['id']]['ndcg@10'] for r in source['per_query']]);rng=np.random.default_rng(SEED)
        bootstrap=d[rng.integers(0,len(d),size=(10000,len(d)))].mean(axis=1)
        flips=(rng.choice((-1,1),size=(20000,len(d)))*d).mean(axis=1)
        comparisons[name]={'query_pairs':len(d),'ndcg_difference':float(d.mean()),'ci95':np.quantile(bootstrap,[.025,.975]).tolist(),
            'bonferroni_ci97_5':np.quantile(bootstrap,[.0125,.9875]).tolist(),'p_raw':float((1+np.count_nonzero(np.abs(flips)>=abs(d.mean())-1e-12))/20001),'seed':SEED}
    previous=0
    for i,(name,value) in enumerate(sorted(comparisons.items(),key=lambda pair:pair[1]['p_raw'])):
        previous=max(previous,min(1,(2-i)*value['p_raw']));value['p_holm']=previous
    seconds=[r['seconds'] for r in hosted.values()]
    search_units=[r['response'].get('usage',{}).get('search_units') for r in hosted.values()]
    known_units=[v for v in search_units if isinstance(v,(int,float)) and math.isfinite(v)]
    return {'methods':means,'paired_ndcg_contrasts':comparisons,'per_query':per_query,
        'hosted_rerank_only_latency':{'mean_seconds':float(np.mean(seconds)),'p50_seconds':float(np.percentile(seconds,50)),'p95_seconds':float(np.percentile(seconds,95))},
        'observed_cost_usd':str(sum(Decimal(r['cost_usd']) for r in hosted.values())),
        'observed_search_units':sum(known_units) if known_units else None,'responses_without_search_units':len(search_units)-len(known_units)}


def main():
    parser=add_provenance_argument(argparse.ArgumentParser());parser.add_argument('--mode',choices=('prepare','run'),default='prepare')
    parser.add_argument('--original',type=Path,default=ROOT/'docs/benchmarks-v2/rerank-results.json');parser.add_argument('--data-dir',type=Path,default=ROOT/'.benchmark-data/scifact')
    parser.add_argument('--base-url',default='https://openrouter.ai/api/v1');parser.add_argument('--key-file',type=Path);parser.add_argument('--max-usd',type=str)
    parser.add_argument('--checkpoint',type=Path,default=ROOT/'.runtime/openrouter-rerank-checkpoint.json');parser.add_argument('--output',type=Path,default=ROOT/'docs/benchmarks-next/openrouter-rerank-results.json')
    args=parser.parse_args();paths=[args.original,args.data_dir/'canonical-records.jsonl',args.data_dir/'queries.jsonl',args.data_dir/'qrels/test.tsv',Path(__file__),ROOT/'docs/benchmarks-next/OPENROUTER-RERANK-PROTOCOL.md'];hashes={str(i):sha256(p) for i,p in enumerate(paths)}
    source,documents,qrels=sources(*paths[:4]);requests=requests_for(source,documents)
    estimate={'requests':len(requests),'documents_per_request':50,'reservation_usd_per_request':str(RESERVATION),'total_reservation_usd':str(RESERVATION*len(requests)),
        'canonical_sha256':hashes['1'],'requested_model':MODEL,'expected_response_model':ACTUAL_MODEL,'input_sha256':digest(requests),'mode':'prepare; no network'}
    if args.mode=='prepare':print(json.dumps(estimate,indent=2));return
    if not args.key_file or args.max_usd is None:parser.error('run requires runtime key-file and explicit max-usd')
    run=BenchmarkRun(allow_dirty=args.allow_dirty)
    def guard():
        if any(sha256(p)!=hashes[str(i)] for i,p in enumerate(paths)):raise RuntimeError('Frozen source/input changed during rerank run.')
        run.checked_provenance()
    state=execute(requests,base_url=args.base_url,key=args.key_file.read_text().strip(),checkpoint=args.checkpoint,max_usd=args.max_usd,input_hashes=hashes,guard=guard)
    guard();result=evaluate(source,qrels,state);guard()
    run.write_json(args.output,{'status':'complete','estimate':estimate,'input_files_sha256':{str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else '<external>/'+p.name:hashes[str(i)] for i,p in enumerate(paths)},
        'parameters':{'requested_model':MODEL,'actual_model':ACTUAL_MODEL,'candidate_k':50,'source_text':'Exact full canonical strings; no local truncation','provider_truncation':'Documented default4096; no returned per-document truncation counters assumed','local_ce':source['parameters']},
        'limitations':['System upgrade comparison, not model-only: Cohere provider-default4096 versus local CE pair limit512.','Network rerank-only clock differs from historical shared-machine total timing.','No generated answer or graph/temporal claim.','Unknown provider training overlap with public SciFact.'],
        'requests':state['requests'],**result})


if __name__=='__main__':main()
