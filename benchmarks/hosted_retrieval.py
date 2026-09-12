"""Opt-in hosted embedding comparison with persistent per-batch accounting.

The endpoint and credential are runtime-only. Frozen source text and model IDs
identify cached batches. A pending or failed dispatch is never silently retried.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
import numpy as np

from benchmarks.provenance import BenchmarkRun
from benchmarks.statistics import comparison_family

ROOT=Path(__file__).resolve().parents[1]


def digest(value):return hashlib.sha256(value).hexdigest()


def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(path)


def post(endpoint,key,body):
    request=Request(endpoint.rstrip('/')+'/embeddings',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    with urlopen(request,timeout=120) as response:return json.load(response)


def validate_response(data,count):
    rows=data.get('data',[])
    if len(rows)!=count or sorted(r.get('index') for r in rows)!=list(range(count)):
        raise ValueError('Embedding response must contain every input index exactly once')
    matrix=np.asarray([r['embedding'] for r in sorted(rows,key=lambda r:r['index'])],dtype=np.float32)
    if matrix.ndim!=2 or matrix.shape[1]!=3072 or not np.isfinite(matrix).all():
        raise ValueError('Expected finite 3072-dimensional text-embedding-3-large vectors')
    norm=np.linalg.norm(matrix,axis=1,keepdims=True)
    if np.any(norm==0):raise ValueError('Zero embedding vector')
    return matrix/norm


class HostedEmbeddings:
    def __init__(self,base,key,cache,max_tokens,send=post,retry_timeout_signature=None):
        from urllib.parse import urlsplit
        parsed=urlsplit(base)
        if parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Invalid credential-free endpoint URL')
        self.base,self.key,self.cache,self.limit,self.send=base,key,Path(cache),max_tokens,send
        self.cache.mkdir(parents=True,exist_ok=True)
        import fcntl
        self.lock=(self.cache/'dispatch.lock').open('a')
        try: fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Embedding cache is already in use; concurrent dispatch refused')
        self.state_path=self.cache/'dispatch.json'
        self.state=json.loads(self.state_path.read_text()) if self.state_path.exists() else {'reserved_tokens':0,'calls':{}}
        self.endpoint_hash=digest(base.rstrip('/').encode())
        self.retry_timeout_signature=retry_timeout_signature
        if retry_timeout_signature:
            prior=self.state['calls'].get(retry_timeout_signature,{})
            if prior.get('status')!='failed_or_uncertain' or prior.get('error_type')!='TimeoutError' or prior.get('prior_attempts'):
                raise ValueError('Explicit recovery permits one recorded timeout only; no unknown or repeated recovery')

    def encode(self,texts,*,model='text-embedding-3-large',token_limit=512):
        import tiktoken
        tokenizer=tiktoken.get_encoding('cl100k_base')
        tokens=[tokenizer.encode(text,disallowed_special=()) for text in texts]
        shortened=[tokenizer.decode(row[:token_limit]) for row in tokens]
        active_positions=[i for i,text in enumerate(shortened) if text.strip()]
        active_texts=[shortened[i] for i in active_positions]
        output=[];started=time.perf_counter();fresh_calls=0
        for start in range(0,len(active_texts),64):
            batch=active_texts[start:start+64]
            body={'model':model,'input':batch,'encoding_format':'float'}
            signature=digest(json.dumps({'endpoint':self.endpoint_hash,'body':body},sort_keys=True).encode())
            path=self.cache/(signature+'.npy');record=self.state['calls'].get(signature)
            if record and record['status']=='complete':
                if digest(path.read_bytes())!=record['array_sha256']:raise ValueError('Corrupt embedding cache')
                matrix=np.load(path,allow_pickle=False)
                if matrix.shape!=(len(batch),3072) or not np.isfinite(matrix).all():raise ValueError('Invalid cached embedding shape')
            else:
                retry=record and signature==self.retry_timeout_signature
                if record and not retry:raise RuntimeError('Prior unresolved embedding dispatch; inspect accounting before retry')
                reservation=sum(len(text.encode()) for text in batch)+512
                if self.state['reserved_tokens']+reservation>self.limit:raise RuntimeError('Hosted embedding token reservation cap reached before dispatch')
                self.state['reserved_tokens']+=reservation
                self.state['calls'][signature]={'status':'pending','reserved_tokens':reservation+(record['reserved_tokens'] if retry else 0),'current_reservation':reservation,'inputs':len(batch),'model':model}
                if retry:
                    self.state['calls'][signature]['prior_attempts']=[record]
                    self.state['calls'][signature]['recovery_note']='Explicit one-time timeout recovery; prior charge remains unknown and fully reserved.'
                    self.retry_timeout_signature=None
                atomic(self.state_path,self.state)
                try:
                    data=self.send(self.base,self.key,body)
                    if data.get('model')!=model: raise ValueError('Unexpected response model; refusing mixed embedding identities')
                    matrix=validate_response(data,len(batch))
                    usage=data.get('usage') or {};used=usage.get('total_tokens')
                    if used is None or used>reservation:raise ValueError('Missing usage or provider usage exceeded conservative reservation')
                    np.save(path,matrix,allow_pickle=False)
                    self.state['calls'][signature].update(status='complete',usage=usage,array_sha256=digest(path.read_bytes()),response_model=data.get('model'))
                    atomic(self.state_path,self.state);fresh_calls+=1
                except Exception as exc:
                    self.state['calls'][signature].update(status='failed_or_uncertain',error_type=type(exc).__name__)
                    atomic(self.state_path,self.state);raise
            output.append(matrix)
            if start%1024==0:print(json.dumps({'stage':'hosted_embedding','rows':min(start+64,len(texts)),'total':len(texts)}),flush=True)
        matrix=np.zeros((len(texts),3072),dtype=np.float32)
        if output:matrix[active_positions]=np.concatenate(output)
        return matrix,{'rows':len(texts),'empty_inputs_excluded':len(texts)-len(active_positions),'model':model,'dimensions':3072,'tokenizer':'cl100k_base','max_input_tokens':token_limit,
            'documents_truncated':sum(len(row)>token_limit for row in tokens),'truncation_fraction':sum(len(row)>token_limit for row in tokens)/len(tokens),
            'source_text_sha256':digest(json.dumps(texts,ensure_ascii=False).encode()),'elapsed_seconds':time.perf_counter()-started,'new_api_requests':fresh_calls}


def ndcg(ranking,gold):
    rel={k:float(v) for k,v in gold.items() if v>0}
    dcg=sum(rel.get(x,0)/np.log2(i+2) for i,x in enumerate(ranking[:10]));ideal=sum(v/np.log2(i+2) for i,v in enumerate(sorted(rel.values(),reverse=True)[:10]))
    return float(dcg/ideal) if ideal else 0.


def main():
    p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--key-file',type=Path,required=True)
    p.add_argument('--datasets',default='scifact');p.add_argument('--max-total-input-tokens',type=int,required=True);p.add_argument('--allow-dirty',action='store_true')
    p.add_argument('--retry-timeout-signature',help='Explicit one-time recovery of this exact timed-out request, retaining its full prior reservation.')
    args=p.parse_args();run=BenchmarkRun(allow_dirty=args.allow_dirty,sources=[Path(__file__),ROOT/'benchmarks/provenance.py',ROOT/'benchmarks/statistics.py'])
    client=HostedEmbeddings(args.base_url,args.key_file.read_text().strip(),ROOT/'.benchmark-data/hosted-embedding-512',args.max_total_input_tokens,retry_timeout_signature=args.retry_timeout_signature)
    results={}
    for name in args.datasets.split(','):
        if name not in {'scifact','nfcorpus','fiqa'}:raise ValueError('Unknown benchmark corpus')
        folder=ROOT/'.benchmark-data/v2'/name/name
        corpus=[json.loads(x) for x in (folder/'corpus.jsonl').read_text().splitlines()]
        questions={x['_id']:x['text'] for x in map(json.loads,(folder/'queries.jsonl').read_text().splitlines())}
        qrels=defaultdict(dict)
        for line in (folder/'qrels/test.tsv').read_text().splitlines()[1:]:
            qid,did,grade=line.split('\t');qrels[qid][did]=int(grade)
        ids=[x['_id'] for x in corpus];texts=['\n'.join(t.strip() for t in (x.get('title',''),x['text']) if t.strip()) for x in corpus]
        qids=sorted(qrels)
        docs,doc_meta=client.encode(texts);queries,query_meta=client.encode([questions[q] for q in qids])
        rankings={};latencies=[]
        for qid,vector in zip(qids,queries):
            start=time.perf_counter();scores=docs@vector
            scores[np.linalg.norm(docs,axis=1)==0]=-np.inf
            order=np.lexsort((np.asarray(ids),-scores))
            rankings[qid]=[ids[i] for i in order if ids[i]!=qid and np.isfinite(scores[i])][:100];latencies.append(time.perf_counter()-start)
        values=[ndcg(rankings[q],qrels[q]) for q in qids]
        results[name]={'corpus_count':len(ids),'query_count':len(qids),'nDCG@10':float(np.mean(values)),'rankings':rankings,'per_query_ndcg':dict(zip(qids,values)),
            'document_embeddings':doc_meta,'query_embeddings':query_meta,'ranking_p50_seconds':float(np.median(latencies))}
        run.write_json(ROOT/'docs/benchmarks-next'/f'hosted-{name}-results.json',{'experiment':'Hosted text-embedding-3-large at512modeltokens; exact dense retrieval','status':'complete','dataset':results[name],
            'endpoint_sha256':client.endpoint_hash,'billing_cost_usd':None,'accounting':client.state,'limitations':['Proxy prices not supplied; token usage is observed, dollars unknown.','Unversioned hosted model alias; no immutable weight identity.','Tokenizer differs from BGE/MiniLM; equal token count does not imply identical text coverage.','Historical/v3 comparisons require their own source and split attribution.'],'predictions_amendment':{'path':'docs/benchmarks-next/HOSTED-PROTOCOL.md','sha256':digest((ROOT/'docs/benchmarks-next/HOSTED-PROTOCOL.md').read_bytes())}})
        print(json.dumps({'stage':'complete','dataset':name,'nDCG@10':float(np.mean(values)),'queries':len(qids)}),flush=True)

if __name__=='__main__':main()
