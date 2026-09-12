"""Exact lexical-overlap postings spike. No production code is changed.

One profile-owned, ordered-exact-text cohort; 64MiB retained-cache admission cap.
Transient building/tokenization and caller-owned source texts are reported outside
that cap. This prototype is evidence for a possible design, not deployed caching.
"""
from __future__ import annotations
from array import array
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_LIMIT=64*1024*1024


class CacheBudgetExceeded(RuntimeError):pass


class TokenPostingsCache:
    def __init__(self,owner='pilot-profile',memory_limit=DEFAULT_LIMIT):
        self.owner=owner;self.memory_limit=memory_limit;self.fingerprint=None;self.document_count=0;self.postings={}

    def _cohort_fingerprint(self,texts):
        digest=sha256()
        owner=self.owner.encode('utf-8');digest.update(len(owner).to_bytes(8,'big'));digest.update(owner)
        digest.update(len(texts).to_bytes(8,'big'))
        for text in texts:
            encoded=text.encode('utf-8');digest.update(len(encoded).to_bytes(8,'big'));digest.update(encoded)
        return digest.hexdigest()

    def memory_breakdown(self):
        instance=sys.getsizeof(self)+sys.getsizeof(self.__dict__)
        attributes=sum(sys.getsizeof(key) for key in self.__dict__)+sum(sys.getsizeof(value) for key,value in self.__dict__.items() if key!='postings')
        dictionary=sys.getsizeof(self.postings)
        token_strings=sum(sys.getsizeof(token) for token in self.postings)
        posting_arrays=sum(sys.getsizeof(posting) for posting in self.postings.values())
        return dict(instance_and_attribute_dict_bytes=instance,attribute_keys_and_scalar_values_bytes=attributes,posting_dict_bytes=dictionary,token_strings_bytes=token_strings,posting_arrays_bytes=posting_arrays,
                    unique_tokens=len(self.postings),posting_positions=sum(len(posting) for posting in self.postings.values()),total_bytes=instance+attributes+dictionary+token_strings+posting_arrays)

    def ensure(self,texts):
        from chronoverse.store import _tokens
        fingerprint=self._cohort_fingerprint(texts)
        if fingerprint==self.fingerprint:return True
        # Single retained cohort: discard the previous index before rebuilding.
        self.postings={};self.fingerprint=fingerprint;self.document_count=len(texts)
        if self.document_count>=2**(8*array('I').itemsize):raise ValueError('Document position exceeds unsigned posting width')
        token_bytes=0;array_bytes=0
        base=self.memory_breakdown()['total_bytes']-sys.getsizeof(self.postings)
        for position,text in enumerate(texts):
            for token in set(_tokens(text)):
                posting=self.postings.get(token)
                if posting is None:
                    posting=array('I');self.postings[token]=posting
                    token_bytes+=sys.getsizeof(token);array_bytes+=sys.getsizeof(posting)
                before=sys.getsizeof(posting);posting.append(position);array_bytes+=sys.getsizeof(posting)-before
            # Admission bound on retained cache; transient per-document token set is separate.
            if base+sys.getsizeof(self.postings)+token_bytes+array_bytes>self.memory_limit:
                self.postings={};self.document_count=0;self.fingerprint=None
                raise CacheBudgetExceeded('Ordered-text cohort exceeds retained cache budget')
        if self.memory_breakdown()['total_bytes']>self.memory_limit:
            self.postings={};self.document_count=0;self.fingerprint=None
            raise CacheBudgetExceeded('Ordered-text cohort exceeds retained cache budget')
        return False

    def score(self,query):
        from chronoverse.store import _tokens
        query_set=set(_tokens(query))
        counts=array('I',[0])*self.document_count
        for token in query_set:
            for position in self.postings.get(token,()):counts[position]+=1
        denominator=len(query_set)
        return [count/denominator if denominator else 0.0 for count in counts]


def baseline(texts,query):
    from chronoverse.store import _tokens
    query_set=set(_tokens(query))
    return [len(query_set&set(_tokens(text)))/len(query_set) if query_set else 0.0 for text in texts]


def self_test():
    cache=TokenPostingsCache()
    cache.ensure(['alpha alpha','alpha beta','gamma'])
    assert cache.score('alpha alpha')==[1.0,1.0,0.0], 'Repeated words must count once per document and query'
    cache.ensure(['alpha','alpha'])
    assert cache.score('alpha')==[1.0,1.0], 'Duplicate documents retain distinct positions'
    assert cache.score('')==[0.0,0.0]
    cache.ensure(['ภาษาไทย alpha','ภาษาไทย','ข้อมูล'])
    assert cache.score('ภาษาไทย alpha')==[1.0,.5,0.0]
    assert cache.score('ภาษาไทย alpha')==baseline(['ภาษาไทย alpha','ภาษาไทย','ข้อมูล'],'ภาษาไทย alpha')
    cache.ensure(['alpha','beta']);old=cache.fingerprint
    assert cache.ensure(['alpha','beta']) is True
    cache.ensure(['beta','alpha']);assert cache.fingerprint!=old
    assert cache.score('alpha')==[0.0,1.0]
    cache.ensure(['beta','alpha','alpha']);assert cache.score('alpha')==[0.0,1.0,1.0]
    cache.ensure(['beta','delta']);assert cache.score('alpha')==[0.0,0.0]
    other=TokenPostingsCache(owner='other-profile');other.ensure(['beta','delta'])
    assert cache.fingerprint!=other.fingerprint, 'Profile ownership participates in the cohort fingerprint'
    cache.ensure([]);assert cache.score('alpha')==[]
    tiny=TokenPostingsCache(memory_limit=4096)
    try:tiny.ensure([' '.join(f'uniquetoken{i}' for i in range(1000))])
    except CacheBudgetExceeded:pass
    else:raise AssertionError('Oversized cohort must not be retained')
    assert tiny.postings=={} and tiny.document_count==0
    print(json.dumps({'self_tests':'passed','cases':['duplicate words','duplicate documents','empty query','Thai Unicode','ordered text change','new document','edited text','profile ownership','empty cohort','64MiB-style admission']}),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'docs/benchmarks-v2/token-postings-pilot.json');args=parser.parse_args()
    self_test()
    if args.self_test:return
    from chronoverse.store import _tokens
    from benchmarks.metrics import latency_summary
    data_dir=ROOT/'.benchmark-data/scifact';records=[json.loads(line) for line in (data_dir/'canonical-records.jsonl').read_text().splitlines()]
    texts=[row['text'] for row in records]
    query_ids=[row['query_id'] for row in json.loads((ROOT/'docs/benchmarks/scifact-results.json').read_text())['per_query']]
    all_queries={row['_id']:row['text'] for row in map(json.loads,(data_dir/'queries.jsonl').read_text().splitlines())}
    queries=[all_queries[qid] for qid in query_ids]
    assert len(texts)==5183 and len(queries)==300
    cache=TokenPostingsCache();clock=time.perf_counter();cache.ensure(texts);postings_build=time.perf_counter()-clock
    clock=time.perf_counter();doc_sets=[set(_tokens(text)) for text in texts];sets_build=time.perf_counter()-clock
    set_bytes=sys.getsizeof(doc_sets)+sum(sys.getsizeof(item)+sum(sys.getsizeof(token) for token in item) for item in doc_sets)
    source_bytes=sys.getsizeof(texts)+sum(sys.getsizeof(text) for text in texts)
    times={name:[] for name in ['production_style_retokenize','cached_document_sets','postings_only','postings_with_exact_text_hash']}
    equality_checks=0;checks=[]
    for number,(qid,query) in enumerate(zip(query_ids,queries),1):
        clock=time.perf_counter();reference=baseline(texts,query);times['production_style_retokenize'].append(time.perf_counter()-clock)
        clock=time.perf_counter();query_set=set(_tokens(query));cached=[len(query_set&tokens)/len(query_set) if query_set else 0.0 for tokens in doc_sets];times['cached_document_sets'].append(time.perf_counter()-clock)
        clock=time.perf_counter();indexed=cache.score(query);times['postings_only'].append(time.perf_counter()-clock)
        clock=time.perf_counter();assert cache.ensure(texts) is True;hashed=cache.score(query);times['postings_with_exact_text_hash'].append(time.perf_counter()-clock)
        assert reference==cached==indexed==hashed,f'Exact document-score mismatch at query {qid}'
        equality_checks+=len(texts)
        checks.append({'query_id':qid,'all_document_scores_exact':True,'documents_compared':len(texts)})
        if number%50==0:print(json.dumps({'stage':'exact_comparison','queries':number,'total':len(queries)}),flush=True)
    summaries={name:latency_summary(values) for name,values in times.items()};post_total=sum(times['postings_with_exact_text_hash'])
    result={'created_at':datetime.now(timezone.utc).isoformat(),'experiment':'exact lexical token-postings pilot; not production',
            'documents':len(texts),'queries':len(queries),'document_score_equality_checks':equality_checks,'all_document_scores_exact':True,
            'tokenizer':'chronoverse.store._tokens, unique tokens per document and query','posting_type':f"array('I'), itemsize={array('I').itemsize}",
            'cohort_key':'SHA-256 over length-prefixed UTF-8 owner, document count, then every exact text in order; hash recomputed in the hash-inclusive condition',
            'cache_scope':'One cohort owned by one profile/Store concept. Old cohort discarded on any ordered-text change. No global cross-profile cache implemented.',
            'memory':{**cache.memory_breakdown(),'limit_bytes':DEFAULT_LIMIT,'within_retained_cache_limit':cache.memory_breakdown()['total_bytes']<=DEFAULT_LIMIT,'cached_document_sets_deep_estimate_bytes':set_bytes,'caller_source_texts_estimate_bytes':source_bytes,'caveat':'sys.getsizeof retained-Python-object estimate includes posting dict, token strings, arrays, object attributes, owner and hash. Not RSS. Transient tokenizer/build/query objects and caller-owned source texts are outside retained admission cap.'},
            'build_seconds':{'postings_including_fingerprint':postings_build,'cached_document_sets':sets_build},'query_timings':summaries,
            'total_query_speedup_vs_hash_inclusive_postings':{'production_style_retokenize':sum(times['production_style_retokenize'])/post_total,'cached_document_sets':sum(times['cached_document_sets'])/post_total},
            'query_checks':checks,'canonical_text_sha256':sha256((data_dir/'canonical-records.jsonl').read_bytes()).hexdigest(),'tokenizer_source_sha256':sha256((ROOT/'backend/chronoverse/store.py').read_bytes()).hexdigest(),
            'python':sys.version,'platform':platform.platform(),'limitations':['Lexical component only; no end-to-end Store latency claim.','300 sequential queries on a shared machine; no throughput or independent repetition claim.','The hash-inclusive condition accounts for exact-cohort validation, but production scope/event projection remains a separate cost.','Memory bound is retained cache admission, not a strict bound on transient build memory or process RSS.','Canonical text changes when evidence visibility changes; any future integration must rebuild or select the matching cohort.']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'stage':'complete','output':str(args.output),'memory_bytes':result['memory']['total_bytes'],'speedups':result['total_query_speedup_vs_hash_inclusive_postings'],'timings':summaries}),flush=True)


if __name__=='__main__':main()
