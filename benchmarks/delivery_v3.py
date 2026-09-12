"""Scaled frozen delivery experiment. No production edits, labels, or answer model in ranking."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import gzip
import json
import os
from pathlib import Path
import re
import tempfile
import time

from benchmarks.delivery_experiment import STRATEGIES
from benchmarks.delivery_projection import DeliveryStore, SQLReceiptStore
from benchmarks.delivery_items import ItemDeliveryStore
from benchmarks.metrics import latency_summary
from benchmarks.provenance import BenchmarkRun, add_provenance_argument, sha256
from chronoverse.models import QueryRequest, timestamp

ROOT=Path(__file__).resolve().parents[1]
ITEM_LABEL='Delivery explicit item view'
CORRECTION_FAMILIES=frozenset({'delayed_correction','delayed_retraction','historical_event_receipt'})


def digest_value(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def gold_units(query, owners):
    claims=set(query['gold_assertion_ids'])
    units={'assertion:'+aid for aid in claims}
    units.update('evidence:'+eid for eid in query['gold_evidence_ids'] if owners.get(eid) not in claims)
    # Legacy event annotations were not questions asking for notice retrieval.
    if query.get('kind')=='event':
        units.update('event:'+eid for eid in query.get('gold_event_ids',[]))
    return units


def compact_result(row):
    return {key:row[key] for key in ('id','item_type','item_id','subject','predicate','object','summary',
            'world','plane','perspective','valid_from','valid_to','recorded_at','effective_valid_to',
            'status','evidence','events','score','score_breakdown') if key in row}


def annotate_compact(query,payload,visible,owners):
    rows=[compact_result(row) for row in payload['results']]
    claims={r['id'] for r in rows if 'item_type' not in r}
    evidence={e['id'] for r in rows for e in r['evidence']}
    events={e['id'] for r in rows for e in r['events']}
    expected=gold_units(query,owners);found=set()
    for aid in claims & set(query['gold_assertion_ids']):
        required={eid for eid in query['gold_evidence_ids'] if owners.get(eid)==aid}
        if required<=evidence:found.add('assertion:'+aid)
    found.update(u for u in expected if u.startswith('evidence:') and u[9:] in evidence)
    found.update(u for u in expected if u.startswith('event:') and u[6:] in events)
    returned={('assertion',aid) for aid in claims}|{('evidence',eid) for eid in evidence}|{('event',eid) for eid in events}
    return {'results':rows,'eligible_count':payload['eligible_count'],
            'gold_support':sorted(expected),'found_support':sorted(found),'missing_support':sorted(expected-found),
            'leaks':[{'type':kind,'id':item} for kind,item in sorted(returned-visible)],
            'retrieval_scope':payload['scope'],'delivery_view':payload['delivery_view']}


def aggregate(rows):
    values=list(rows.values());answerable=[r for r in values if r['gold_support']];empty=[r for r in values if not r['gold_support']]
    tp=sum(len(r['found_support']) for r in values);gold=sum(len(r['gold_support']) for r in values)
    returned=sum(len(r['results']) for r in values)
    ratio=lambda n,d:n/d if d else None
    return {'query_count':len(values),'answerable_queries':len(answerable),'empty_queries':len(empty),
            'support_precision':ratio(tp,returned),'support_recall':ratio(tp,gold),
            'complete_support_rate':ratio(sum(not r['missing_support'] for r in answerable),len(answerable)),
            'exact_support_set_rate':ratio(sum(not r['missing_support'] and len(r['results'])==len(r['found_support']) for r in values),len(values)),
            'empty_abstention_rate':ratio(sum(not r['results'] for r in empty),len(empty)),
            'false_abstention_rate':ratio(sum(not r['results'] for r in answerable),len(answerable)),
            'leakage_query_rate':ratio(sum(bool(r['leaks']) for r in values),len(values)),
            'unreceived_items_returned':sum(len(r['leaks']) for r in values),
            'supported_units_returned':tp,'gold_support_units':gold,'returned_context_units':returned}


def grouped_metrics(rows,queries,field):
    groups=defaultdict(dict)
    for q in queries:groups[q.get(field,'unspecified')][q['id']]=rows[q['id']]
    return {key:aggregate(group) for key,group in sorted(groups.items())}


def projection_signature(rows):
    # Full projected text is hashed before scoring; payloads are not copied into
    # every result. Scores/explanations are computed downstream and excluded.
    return digest_value([{key:r.get(key) for key in ('id','item_type','item_id','subject','predicate','object','summary',
                        'world','plane','perspective','evidence','events','status','effective_valid_to')} for r in rows])


def capture_projection(store):
    original=store._eligible
    def capture(request):
        rows=original(request)
        store.last_projection={'count':len(rows),'sha256':projection_signature(rows)}
        return rows
    store._eligible=capture


def source_catalog(store):
    owners={};source_times={};assertions=[]
    for record in store._db.execute('SELECT payload FROM assertions ORDER BY id'):
        a=json.loads(record[0]);assertions.append(a);source_times[('assertion',a['id'])]=a['recorded_at']
        for e in a['evidence']:owners[e['id']]=a['id'];source_times[('evidence',e['id'])]=e['recorded_at']
    for record in store._db.execute('SELECT payload FROM events'):
        e=json.loads(record[0]);source_times[('event',e['id'])]=e['recorded_at']
    return owners,source_times,assertions


def entity_versions(question,assertions):
    # Uses question text and corpus subject catalog only, never gold IDs/entity.
    subjects={a['subject'] for a in assertions if a['subject'].casefold() in question.casefold()}
    if not subjects:return {'entity_from_question':None,'contexts':[]}
    longest=max(map(len,subjects));subjects={s for s in subjects if len(s)==longest}
    if len(subjects)!=1:return {'entity_from_question':None,'contexts':[],'ambiguity':'multiple longest subject matches'}
    entity=next(iter(subjects))
    return {'entity_from_question':entity,'contexts':[{k:a[k] for k in ('id','subject','predicate','object','summary','valid_from','valid_to','recorded_at','evidence')} for a in assertions if a['subject']==entity]}


def require_stable(method,query_id,first,current):
    if current!=first:
        raise RuntimeError(f'Unstable retrieval signature for method {method}, query {query_id}; refusing complete results.')
    return 1


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    parser.add_argument('--fixture',type=Path,default=ROOT/'benchmarks/data/delivery-v3.json.gz')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'docs/benchmarks-delivery-v3')
    parser.add_argument('--splits',nargs='+',default=['dev','test','compatibility'])
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--embedding-mode',choices=['semantic','hashed'],default='semantic')
    parser.add_argument('--pilot-limit',type=int,default=0,help='Unscored first N DEV requests only; diagnostic timings, never test metrics.')
    args=parser.parse_args()
    if args.repeats<2:parser.error('--repeats must be >=2 for stability evidence')
    run_context=BenchmarkRun(allow_dirty=args.allow_dirty)
    fixture_hash=sha256(args.fixture)
    raw_fixture=gzip.decompress(args.fixture.read_bytes()) if args.fixture.suffix=='.gz' else args.fixture.read_bytes()
    raw_fixture_hash=hashlib.sha256(raw_fixture).hexdigest();fixture=json.loads(raw_fixture)
    queries=[q for q in fixture['queries'] if q.get('split','compatibility') in args.splits]
    if args.pilot_limit:
        queries=[q for q in queries if q.get('split')=='dev'][:args.pilot_limit]
        if not queries:parser.error('pilot requires DEV queries')
    if not queries:parser.error('no selected queries')
    os.environ['CHRONOVERSE_EMBEDDINGS']=args.embedding_mode
    os.environ.setdefault('CHRONOVERSE_MODEL_CACHE',str(ROOT/'.model-cache'))
    os.environ.setdefault('HF_HUB_OFFLINE','1')
    from chronoverse import semantic
    started=time.perf_counter();methods={};contexts={};comparisons={}
    with tempfile.TemporaryDirectory(prefix='delivery-v3-') as temporary:
        path=Path(temporary)/'ledger.sqlite3'
        with DeliveryStore.from_fixture(path,fixture) as delivery, SQLReceiptStore(path,seed=False) as sql, ItemDeliveryStore(path,seed=False) as item:
            item.receipts=delivery.receipts
            owners,source_times,assertions=source_catalog(delivery)
            build_seconds=time.perf_counter()-started
            for store in (delivery,sql,item):capture_projection(store)
            arms=[(label,sql if strategy=='sql' else delivery,strategy) for label,strategy in STRATEGIES.items()]
            arms.append((ITEM_LABEL,item,'delivery'))
            for label,store,strategy in arms:
                store.strategy=strategy;rows={};first_signatures={};timings=[[] for _ in range(args.repeats)];stable=0
                for repeat in range(args.repeats):
                    for q in queries:
                        fields={k:v for k,v in q['scope'].items() if k!='received_by'}
                        request=QueryRequest(query=q['query'],limit=5,**fields)
                        semantic._embed.cache_clear() # fresh query embedding for every arm/repeat
                        before=time.perf_counter()
                        payload=store.query_for(q['recipient_id'],q['scope']['received_by'],request)
                        elapsed=time.perf_counter()-before;timings[repeat].append(elapsed)
                        signature=digest_value({'results':[compact_result(r) for r in payload['results']],
                                                'projection':store.last_projection,'graph':payload['graph']})
                        if repeat==0:first_signatures[q['id']]=signature
                        else:stable+=require_stable(label,q['id'],first_signatures[q['id']],signature)
                        if repeat==args.repeats-1:
                            visible=sql.visible_keys(q['recipient_id'],q['scope']['received_by'],q['scope']['known_at'])
                            known=timestamp(q['scope']['known_at'])
                            visible={key for key in visible if source_times.get(key,'9999')<=known}
                            row=annotate_compact(q,payload,visible,owners)
                            row.update(seconds=elapsed,signature_sha256=signature,candidate_projection=dict(store.last_projection))
                            rows[q['id']]=row
                    print(json.dumps({'stage':'repeat_complete','method':label,'repeat':repeat+1,'queries':len(queries),'seconds':sum(timings[repeat])}),flush=True)
                methods[label]={'per_query':rows,'latency_by_repeat':[latency_summary(t) for t in timings],
                    'stability':{'matching_repeated_signatures':stable,'comparisons':len(queries)*(args.repeats-1)}}
                if not args.pilot_limit:
                    methods[label].update(metrics=aggregate(rows),by_split=grouped_metrics(rows,queries,'split'),
                                          by_family=grouped_metrics(rows,queries,'family'),by_kind=grouped_metrics(rows,queries,'kind'),
                        by_split_family={split:grouped_metrics(rows,[q for q in queries if q.get('split','unspecified')==split],'family') for split in sorted({q.get('split','unspecified') for q in queries})},
                        diagnostics={'event_notice_retrieval':aggregate({q['id']:rows[q['id']] for q in queries if q.get('kind')=='event'}),
                            'standalone_evidence_retrieval':aggregate({q['id']:rows[q['id']] for q in queries if q.get('kind')=='evidence' or (not q['gold_assertion_ids'] and q['gold_evidence_ids'])}),
                            'correction_claim_support':aggregate({q['id']:rows[q['id']] for q in queries if q.get('kind')!='event' and q.get('family') in CORRECTION_FAMILIES})})
                run_context.write_json(args.output_dir/'progress.json',{'status':'running','fixture_sha256':fixture_hash,
                    'completed_methods':list(methods),'methods':methods,'pilot_unscored':bool(args.pilot_limit)})
                if label in ('Filter after projection',ITEM_LABEL):
                    key='D_post_projection_receipts' if label=='Filter after projection' else 'E_delivery_explicit_item_view'
                    contexts[key]={qid:row['results'] for qid,row in rows.items()}
            ordinary=methods['Ordinary SQL receipt filter']['per_query'];projected=methods['Delivery projection']['per_query']
            comparisons={'query_count':len(queries),
                         'sql_delivery_identical_results':sum(digest_value(ordinary[q['id']]['results'])==digest_value(projected[q['id']]['results']) for q in queries),
                         'sql_delivery_identical_candidate_projections':sum(ordinary[q['id']]['candidate_projection']==projected[q['id']]['candidate_projection'] for q in queries)}
            contexts['B_all_versions_question_entity']={q['id']:entity_versions(q['query'],assertions) for q in queries}
    if sha256(args.fixture)!=fixture_hash:raise RuntimeError('Fixture changed during run')
    result={'status':'pilot_unscored' if args.pilot_limit else 'complete','experiment':'Scaled delivery v3 with separately labeled item-view extension',
            'fixture_sha256':fixture_hash,'fixture_raw_sha256':raw_fixture_hash,'fixture_path':str(args.fixture),'fixture_counts':fixture.get('counts'),
            'query_manifest':queries,'methods':methods,'comparison':comparisons,'ledger_build_seconds':build_seconds,
            'elapsed_seconds':time.perf_counter()-started,'embedding_mode':args.embedding_mode,
            'model':{'name':semantic.MODEL,'identity':semantic.model_identity() if args.embedding_mode=='semantic' else 'hashed-lexical-256'},
            'ranking':'Unchanged Store top5: 0.35 lexical + 0.50 cosine + 0.15 one-hop graph; semantic threshold 0.28.',
            'paid_api_calls':0,'correction_primary_families':sorted(CORRECTION_FAMILIES),'item_view':{'notice_words':sorted(__import__('benchmarks.delivery_items',fromlist=['NOTICE_WORDS']).NOTICE_WORDS),
                'evidence_scope':'Parent original validity and dimensions; ignore lifecycle; omit evidence already attached to an eligible assertion context.',
                'notice_scope':'Explicit notice wording; source/receipt/dimensions; future effective notices allowed; parent original validity does not restrict notices.'},
            'limitations':['Synthetic scenario-template test with shared mechanism vocabulary; not independent real-world samples.',
                'Five original arms are assertion-only; item view adds a different capability and may retrieve stale-but-received evidence.',
                'Gold event annotations count only for explicit event-kind questions; event-only queries are answerable, never empty-gold abstention.',
                'Timings include compact candidate-signature instrumentation; first repeat includes incremental vector preparation; later repeats share persisted document vectors and encode each query fresh.',
                'Arms share an immutable ledger and exact-text vector table; these are not independent cold-index timing comparisons.',
                'No generated answers or answer-sufficiency model. Irrelevant received context remains possible.',
                'Receipt metadata is explicit availability, not truth, endorsement, or human knowledge.']}
    run_context.write_json(args.output_dir/'results.json',result)
    run_context.write_json(args.output_dir/'retrieval-contexts.json',{'fixture_sha256':fixture_hash,'query_manifest':queries,
        'arms':contexts,'pending_arms':['A_raw_dense_original_versions','C_dense_local_crossencoder'],
        'context_policy':'B uses only question text to match longest unique corpus subject. D/E are exact returned top5 with dates and source passages; no gold-derived filtering.'})
    print(json.dumps({'stage':'complete','output':str(args.output_dir),'comparison':comparisons}),flush=True)


if __name__=='__main__':main()
