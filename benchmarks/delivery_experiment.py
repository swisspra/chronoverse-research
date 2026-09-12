"""Fixed local delivery-receipt ablation; no production writes or label tuning."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import tempfile
import time

from benchmarks.metrics import latency_summary
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
from benchmarks.delivery_projection import DeliveryStore, SQLReceiptStore
from chronoverse.models import QueryRequest, timestamp

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/benchmarks-delivery'
FIXTURE = ROOT / 'benchmarks/data/delivery-v1.json'
FROZEN_HASH = '6e7777224c18312f94a70368805dc4478a72362dc04bd8e4cf563288c5f0120b'
STRATEGIES = {'Global temporal':'global','Scalar clock':'scalar',
              'Filter after projection':'post_projection',
              'Ordinary SQL receipt filter':'sql', 'Delivery projection':'delivery'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def support_units(query):
    claims = set(query['gold_assertion_ids'])
    units = {'assertion:'+aid for aid in claims}
    units.update('evidence:'+eid for eid in query['gold_evidence_ids'] if eid.rsplit('-e',1)[0] not in claims)
    return units


def annotate(query, payload, visible):
    rows = payload['results']
    got_claims = {r['id'] for r in rows}
    got_evidence = {e['id'] for r in rows for e in r['evidence']}
    expected = support_units(query)
    found = set()
    for aid in got_claims & set(query['gold_assertion_ids']):
        required = {eid for eid in query['gold_evidence_ids'] if eid.rsplit('-e',1)[0]==aid}
        if required <= got_evidence:
            found.add('assertion:'+aid)
    found.update(unit for unit in expected if unit.startswith('evidence:') and unit[9:] in got_evidence)
    returned = [('assertion',r['id']) for r in rows]
    returned += [('evidence',e['id']) for r in rows for e in r['evidence']]
    returned += [('event',e['id']) for r in rows for e in r['events']]
    leaks = [{'type':kind,'id':item} for kind,item in sorted(set(returned)-visible)]
    return {'results':rows, 'eligible_count':payload['eligible_count'], 'leaks':leaks,
            'missing_support':sorted(expected-found), 'gold_support':sorted(expected),
            'found_support':sorted(found), 'candidate_projection':payload.get('candidate_projection',[]),
            'retrieval_scope':payload['scope'], 'delivery_view':payload['delivery_view']}


def aggregate(rows):
    tp = sum(len(r['found_support']) for r in rows.values())
    expected = sum(len(r['gold_support']) for r in rows.values())
    # Each result is an assertion context unit. Orphan passages are expected
    # support units too; this assertion-centric retriever cannot return them alone.
    returned = sum(len(r['results']) for r in rows.values())
    answerable = [r for r in rows.values() if r['gold_support']]
    empty = [r for r in rows.values() if not r['gold_support']]
    return {'query_count':len(rows), 'answerable_queries':len(answerable), 'empty_queries':len(empty),
            'support_precision':tp/returned if returned else 0.0,
            'support_recall':tp/expected if expected else 0.0,
            'complete_support_rate':sum(not r['missing_support'] for r in answerable)/len(answerable),
            'exact_support_set_rate':sum(not r['missing_support'] and len(r['results'])==len(r['found_support']) for r in rows.values())/len(rows),
            'empty_abstention_rate':sum(not r['results'] for r in empty)/len(empty),
            'false_abstention_rate':sum(not r['results'] for r in answerable)/len(answerable),
            'leakage_query_rate':sum(bool(r['leaks']) for r in rows.values())/len(rows),
            'unreceived_items_returned':sum(len(r['leaks']) for r in rows.values()),
            'supported_units_returned':tp, 'gold_support_units':expected, 'returned_assertion_contexts':returned}


def signature(rows):
    return [(r['id'],r['score'],tuple(e['id'] for e in r['evidence']),tuple(e['id'] for e in r['events']),r['status'],r['effective_valid_to']) for r in rows]


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    args=parser.parse_args()
    run_context=BenchmarkRun(allow_dirty=args.allow_dirty)
    assert digest(FIXTURE)==FROZEN_HASH, 'Fixture changed after preflight freeze.'
    fixture = json.loads(FIXTURE.read_text())
    unique = {(q['recipient_id'],q['query'],json.dumps(q['scope'],sort_keys=True)) for q in fixture['queries']}
    assert len(unique)==len(fixture['queries'])==50
    os.environ['CHRONOVERSE_EMBEDDINGS']='semantic'
    os.environ.setdefault('CHRONOVERSE_MODEL_CACHE',str(ROOT/'.model-cache'))
    os.environ.setdefault('HF_HUB_OFFLINE','1')
    from chronoverse import semantic
    files = ['benchmarks/delivery_projection.py','benchmarks/delivery_experiment.py','benchmarks/delivery_fixture.py',
             'backend/chronoverse/store.py','backend/chronoverse/semantic.py','backend/chronoverse/vector_index.py','backend/chronoverse/lexical_index.py','backend/chronoverse/models.py']
    source_before = {name:digest(ROOT/name) for name in files}
    started = time.perf_counter()
    queries = fixture['queries']
    methods = {}
    with tempfile.TemporaryDirectory(prefix='chronoverse-delivery-') as temporary:
        stores = {}
        try:
            for label, strategy in STRATEGIES.items():
                cls = SQLReceiptStore if strategy=='sql' else DeliveryStore
                store = cls.from_fixture(Path(temporary)/(strategy+'.sqlite3'),fixture)
                store.strategy = strategy
                stores[label] = store
            reference = stores['Ordinary SQL receipt filter']
            source_times = {}
            for row in reference._db.execute('SELECT payload FROM assertions'):
                assertion = json.loads(row[0]);source_times[('assertion',assertion['id'])]=assertion['recorded_at']
                source_times.update({('evidence',e['id']):e['recorded_at'] for e in assertion['evidence']})
            for row in reference._db.execute('SELECT payload FROM events'):
                event=json.loads(row[0]);source_times[('event',event['id'])]=event['recorded_at']

            def run(store, query):
                fields={k:v for k,v in query['scope'].items() if k!='received_by'}
                request=QueryRequest(query=query['query'],limit=5,**fields)
                before=time.perf_counter()
                payload=store.query_for(query['recipient_id'],query['scope']['received_by'],request)
                seconds=time.perf_counter()-before
                # Untimed all-candidate projection comparison, excluding scores.
                with store._lock:
                    store._delivery_context=(query['recipient_id'],timestamp(query['scope']['received_by']))
                    try:
                        actual=request.model_copy(update={'known_at':min(timestamp(request.known_at),timestamp(query['scope']['received_by']))}) if store.strategy=='scalar' else request
                        candidates=store._eligible(actual)
                    finally:
                        store._delivery_context=None
                payload['candidate_projection']=[{k:row[k] for k in ('id','evidence','events','status','effective_valid_to')} for row in candidates]
                visible=reference.visible_keys(query['recipient_id'],query['scope']['received_by'],query['scope']['known_at'])
                visible={key for key in visible if source_times.get(key,'9999')<=timestamp(query['scope']['known_at'])}
                return {**annotate(query,payload,visible),'seconds':seconds}

            for label,store in stores.items():
                for query in queries:
                    run(store,query)
                print(json.dumps({'stage':'prepared','method':label}),flush=True)
            preparation=time.perf_counter()-started
            for label,store in stores.items():
                rows={}
                for query in queries:
                    semantic._embed.cache_clear()
                    rows[query['id']]=run(store,query)
                methods[label]={'metrics':aggregate(rows),'latency':latency_summary([r['seconds'] for r in rows.values()]),'per_query':rows}
                print(json.dumps({'stage':'measured','method':label,**methods[label]['metrics']}),flush=True)
        finally:
            for store in stores.values():
                store.close()
    ordinary=methods['Ordinary SQL receipt filter']['per_query']
    delivery=methods['Delivery projection']['per_query']
    comparison={'queries':len(queries),
                'identical_top5_ids_and_scores':sum(signature(ordinary[q['id']]['results'])==signature(delivery[q['id']]['results']) for q in queries),
                'identical_candidate_projections':sum(ordinary[q['id']]['candidate_projection']==delivery[q['id']]['candidate_projection'] for q in queries)}
    assert {name:digest(ROOT/name) for name in files}==source_before, 'Source changed during experiment.'
    assert digest(FIXTURE)==FROZEN_HASH
    result={'status':'complete','experiment':'Classical delivery-specific receipt/time ablation v1',
            'fixture_sha256':FROZEN_HASH,'fixture':fixture,'methods':methods,'comparison':comparison,
            'preparation_seconds':preparation,'total_seconds':time.perf_counter()-started,
            'model':{'name':semantic.MODEL,'identity':semantic.model_identity(),'ranking':'Unchanged Store:0.35lexical+0.50cosine+0.15one-hopgraph; semantic threshold0.28; top5'},
            'source_sha256':source_before,'environment':{'python':platform.python_version(),'platform':platform.platform(),'packages':{p:importlib.metadata.version(p) for p in ('fastembed','onnxruntime','numpy')}},
            'protocol':'PROTOCOL.md','paid_api_calls':0,
            'limitations':[
                'Small manually authored synthetic fixture with shared vocabulary; no independently authored public benchmark or generalization claim.',
                '50 unique questions,18 assertions,3 lifecycle events: these are diagnostic scenario checks, not50 independent real-world samples.',
                'Receipt represents explicit availability, not endorsement, truth or comprehension.',
                'No generated answers: metrics evaluate retrieved context/support, not factual answer accuracy.',
                'The SQL receipt filter receives the same metadata and ranker. Equivalence establishes conventional implementability, not a novel retrieval advantage.',
                'All methods remain assertion-centric. A received standalone passage without its parent assertion receipt (oq41) can be missed; it remains answerable gold.',
                'Gold lifecycle event IDs are preserved as diagnostic annotations; events attached to retired claims may not be returned by this active-assertion API.',
                'Delivery projection removes unseen context but does not add an answer-sufficiency classifier; irrelevant received context may still be returned.',
                'Warm document/model state and fresh query encoding are timed; methods have different eligible corpus sizes and shared-machine timings are diagnostic only.',
                'Production app, MCP, user profiles and original benchmark artifacts are unchanged; these are isolated lab adapters.'
            ]}
    OUT.mkdir(parents=True,exist_ok=True)
    run_context.write_json(OUT/'results.json',result)
    (OUT/'fixture.json').write_bytes(FIXTURE.read_bytes())
    for name in files:
        dest=OUT/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
    print(json.dumps({'stage':'complete','output':str(OUT/'results.json'),'comparison':comparison}),flush=True)


if __name__=='__main__':
    main()
