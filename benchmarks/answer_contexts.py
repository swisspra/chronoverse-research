"""Five fixed answer contexts; retrieval never receives gold annotations."""
from __future__ import annotations
import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import random
import re

from benchmarks.answer_experiment import PROMPT
from benchmarks.provenance import BenchmarkRun, add_provenance_argument, sha256

ROOT=Path(__file__).resolve().parents[1]
SEED=20260912


def load(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def instant(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    return (parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def pilot_queries(queries,size=50):
    test=sorted([q for q in queries if q['split']=='test'],key=lambda q:q['id'])
    if len(test)!=500:raise ValueError('Expected complete fixed 500-query TEST set.')
    if size==500:return test
    if size!=50:raise ValueError('Only preregistered pilot50 or full500 supported.')
    groups=defaultdict(list)
    for q in test:groups[q['family']].append(q)
    if len(groups)!=9:raise ValueError('Expected all nine TEST families.')
    rng=random.Random(SEED)
    for family in sorted(groups):rng.shuffle(groups[family])
    chosen=[]
    while len(chosen)<size:
        for family in sorted(groups):
            if groups[family] and len(chosen)<size:chosen.append(groups[family].pop())
    return sorted(chosen,key=lambda q:q['id'])


def query_input(query):
    return {'id':query['id'],'question':query['query'],'recipient_id':query['recipient_id'],'scope':deepcopy(query['scope'])}


def catalog(fixture):
    assertions=deepcopy(fixture['assertions']);items={};owners={}
    for a in assertions:
        items['assertion:'+a['id']]=a
        for i,e in enumerate(a['evidence'],1):
            e['id']=e.get('id') or f"{a['id']}-e{i}"
            e['recorded_at']=e.get('recorded_at') or a['recorded_at']
            items['evidence:'+e['id']]=e;owners[e['id']]=a['id']
    for e in fixture['events']:items['event:'+e['id']]=deepcopy(e)
    receipts=defaultdict(list)
    for r in fixture['receipts']:receipts[(r['recipient_id'],r['item_type']+':'+r['item_id'])].append(r)
    return assertions,items,owners,receipts


def entity_context(question,assertions,events):
    matches=set(re.findall(r'\bTest monitoring station [0-9]+\b',question))
    if len(matches)!=1:raise ValueError('B requires one unambiguous question-derived station.')
    entity=matches.pop();selected=[a for a in assertions if a['subject']==entity]
    ids={a['id'] for a in selected}
    return selected,[e for e in events if e['assertion_id'] in ids],entity


def candidate_inventory(fixture):
    """All raw item types; no query, gold, receipt or eligibility input."""
    assertions,_,_,_=catalog(fixture);units=[]
    for a in assertions:
        units.append({'id':'assertion:'+a['id'],'rows':[a],
            'text':' '.join([a['subject'],a['predicate'],a['object'],a['summary'],*[e['text'] for e in a['evidence']]])})
        for e in a['evidence']:
            units.append({'id':'evidence:'+e['id'],'rows':[{'item_type':'evidence','evidence':[e]}],
                'text':' '.join([a['subject'],a['predicate'],e.get('title',''),e['text']])})
    for event in fixture['events']:
        # A notice is only the notice's own text/metadata, never replacement text.
        units.append({'id':'event:'+event['id'],'rows':[{'item_type':'event','events':[deepcopy(event)]}],
            'text':json.dumps({k:event[k] for k in ('id','assertion_id','type','reason','source','effective_at','recorded_at','replacement_id') if k in event},sort_keys=True,ensure_ascii=False)})
    if len({u['id'] for u in units})!=len(units):raise ValueError('Duplicate typed candidate ID.')
    return units


def serialize_context(rows,extra_events,query,receipts,*,bounded_receipts):
    """Serialize only supplied projected fields; never reattach hidden evidence."""
    found={}
    def add(kind,id,value):
        typed=kind+':'+id
        delivered=receipts.get((query['recipient_id'],typed),[])
        if bounded_receipts:delivered=[r for r in delivered if instant(r['recorded_at'])<=instant(query['scope']['known_at']) and instant(r['received_at'])<=instant(query['scope']['received_by'])]
        fields={k:v for k,v in value.items() if k not in ('evidence','events','score','score_breakdown','explanation')}
        fields['receipts_for_recipient']=[{k:r[k] for k in ('received_at','recorded_at')} for r in delivered]
        found.setdefault(typed,{'id':typed,'text':json.dumps(fields,ensure_ascii=False,sort_keys=True)})
    for row in rows:
        if not row.get('item_type'):add('assertion',row['id'],row)
        for e in row.get('evidence',[]):add('evidence',e['id'],e)
        for e in row.get('events',[]):add('event',e['id'],e)
    for e in extra_events:add('event',e['id'],e)
    return list(found.values())


def scoring_metadata(query,items,owners,receipts):
    # Gold is evaluated here only, after all five contexts have been constructed.
    known=instant(query['scope']['known_at']);at=instant(query['scope']['received_by']);valid=instant(query['scope']['valid_at']);recipient=query['recipient_id']
    visible={typed for typed,value in items.items() if instant(value['recorded_at'])<=known and any(instant(r['recorded_at'])<=known and instant(r['received_at'])<=at for r in receipts.get((recipient,typed),[]))}
    interval_stale=set()
    for typed,a in items.items():
        if not typed.startswith('assertion:'):continue
        if valid<instant(a['valid_from']) or (a.get('valid_to') is not None and valid>=instant(a['valid_to'])):interval_stale.add(typed)
    stale=set(interval_stale)
    for typed,e in items.items():
        if typed.startswith('event:') and typed in visible and e['type'] in ('supersede','correct','retract') and instant(e['effective_at'])<=valid:stale.add('assertion:'+e['assertion_id'])
    stale.update('evidence:'+eid for eid,aid in owners.items() if 'assertion:'+aid in interval_stale)
    claims=set(query['gold_assertion_ids']);gold={'assertion:'+aid for aid in claims}
    gold.update('evidence:'+eid for eid in query['gold_evidence_ids'] if owners.get(eid) not in claims)
    if query.get('kind')=='event':gold.update('event:'+eid for eid in query['gold_event_ids'])
    groups=[]
    for required in sorted(gold):
        alternatives={required}
        if required.startswith('assertion:'):
            alternatives.update('evidence:'+eid for eid in query['gold_evidence_ids'] if owners.get(eid)==required.split(':',1)[1])
        if required in stale:alternatives=set()
        # Gold defines the required support; receipt/clock eligibility defines
        # which literal item IDs may satisfy it. Never resurrect a hidden parent.
        groups.append({'required_id':required,'acceptable_ids':sorted((alternatives&visible)-stale)})
    return {'expected_answers':query['expected_answers'],'gold_support_ids':sorted(gold),
            'support_equivalence_groups':groups,
            'visible_ids':sorted(visible),'stale_ids':sorted(stale),'answerable':bool(gold),
            'family':query['family'],'event_only':query.get('kind')=='event'}


def build_manifests(fixture,result,queries,dense_pools,reranked):
    assertions,items,owners,receipts=catalog(fixture);by_id={u['id']:u for u in candidate_inventory(fixture)}
    out=[];trace={}
    for q in queries:
        public=query_input(q);qid=q['id'];a_ids=dense_pools[qid];c_ids=reranked[qid]
        if len(a_ids)!=50 or len(c_ids)!=50 or len(set(a_ids))!=50 or set(a_ids)!=set(c_ids):raise ValueError('C must reorder exactly A top50.')
        b_rows,b_events,entity=entity_context(public['question'],assertions,fixture['events'])
        raw={'A':[row for aid in a_ids[:5] for row in by_id[aid]['rows']],'B':b_rows,'C':[row for aid in c_ids[:5] for row in by_id[aid]['rows']],
             'D':result['methods']['Filter after projection']['per_query'][qid]['results'],
             'E':result['methods']['Delivery explicit item view']['per_query'][qid]['results']}
        contexts={arm:serialize_context(rows,b_events if arm=='B' else [],public,receipts,bounded_receipts=arm in ('D','E')) for arm,rows in raw.items()}
        metadata=scoring_metadata(q,items,owners,receipts)
        for arm in 'ABCDE':out.append({'query_id':qid,'arm':arm,'question':public['question'],'recipient_id':public['recipient_id'],
            **{k:public['scope'][k] for k in ('valid_at','known_at','received_by')},'context':contexts[arm],
            'prompt_sha256':sha256(PROMPT),**metadata})
        trace[qid]={'dense_top50':a_ids,'cross_encoder_top50':c_ids,'B_question_entity':entity,
                    'context_ids':{arm:[r['id'] for r in context] for arm,context in contexts.items()}}
    return out,trace


def rank_candidates(units,queries,cache_dir):
    import torch
    from sentence_transformers import SentenceTransformer,CrossEncoder
    if not torch.backends.mps.is_available():raise RuntimeError('Frozen context runtime requires local MPS; no silent runtime switch.')
    dense=SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2',device='mps',cache_folder=str(cache_dir),local_files_only=True)
    dense.max_seq_length=256
    texts=[u['text'] for u in units]
    vectors=dense.encode(texts,batch_size=64,normalize_embeddings=True,show_progress_bar=False)
    qvectors=dense.encode([q['question'] for q in queries],batch_size=32,normalize_embeddings=True,show_progress_bar=False)
    ids=[u['id'] for u in units];pools={};reranked={}
    cross=CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2',device='mps',cache_folder=str(cache_dir),max_length=512,local_files_only=True)
    for q,qvector in zip(queries,qvectors,strict=True):
        scores=vectors@qvector
        positions=sorted(range(len(ids)),key=lambda i:(-float(scores[i]),ids[i]))[:50]
        logits=cross.predict([(q['question'],texts[i]) for i in positions],batch_size=16,show_progress_bar=False,activation_fn=torch.nn.Identity())
        pools[q['id']]=[ids[i] for i in positions]
        reranked[q['id']]=[ids[i] for i,s in sorted(zip(positions,logits),key=lambda pair:(-float(pair[1]),ids[pair[0]]))]
    torch.mps.synchronize()
    return pools,reranked


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    parser.add_argument('--fixture',type=Path,default=ROOT/'benchmarks/data/delivery-v3.json.gz')
    parser.add_argument('--results',type=Path,default=ROOT/'docs/benchmarks-delivery-v3/results.json')
    parser.add_argument('--size',type=int,choices=(50,500),default=50)
    parser.add_argument('--reuse-ranking-manifest',type=Path,help='Reuse exact frozen A/C ranks; rebuild scoring metadata without model inference.')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/benchmarks-next/answer-contexts-50.jsonl')
    args=parser.parse_args();run_context=BenchmarkRun(allow_dirty=args.allow_dirty)
    inputs={path:sha256(path) for path in (args.fixture,args.results,PROMPT)}
    if args.reuse_ranking_manifest:inputs[args.reuse_ranking_manifest]=sha256(args.reuse_ranking_manifest)
    artifacts={p:sha256(p)
        for folder in ('models--sentence-transformers--all-MiniLM-L6-v2','models--cross-encoder--ms-marco-MiniLM-L6-v2')
        for p in (ROOT/'.model-cache/mps'/folder/'snapshots').rglob('*') if p.is_file()}
    if not artifacts:raise RuntimeError('Local model artifact snapshots are missing; no implicit download.')
    fixture=load(args.fixture);result=load(args.results)
    if result['status']!='complete':raise ValueError('Actual delivery results must be complete.')
    if result.get('fixture_sha256')!=sha256(args.fixture):raise ValueError('Retrieval result fixture hash does not match the supplied fixture.')
    queries=pilot_queries(fixture['queries'],args.size)
    recorded={q['id']:q for q in result['query_manifest']}
    if any(recorded.get(q['id'])!=q for q in queries):raise ValueError('Selected query metadata differs from the frozen retrieval query manifest.')
    units=candidate_inventory(fixture)
    if args.reuse_ranking_manifest:
        prior=load(args.reuse_ranking_manifest)
        if prior['fixture_sha256']!=inputs[args.fixture] or prior['retrieval_result_sha256']!=inputs[args.results] or prior['prompt_sha256']!=inputs[PROMPT]:raise ValueError('Frozen ranking input hashes mismatch.')
        if prior['selected_query_ids']!=[q['id'] for q in queries]:raise ValueError('Frozen ranking query selection mismatch.')
        current_models={str(p.relative_to(ROOT/'.model-cache/mps')):value for p,value in artifacts.items()}
        if prior['model_artifact_sha256']!=current_models:raise ValueError('Frozen ranking model artifact hashes mismatch.')
        pools={q['id']:prior['trace'][q['id']]['dense_top50'] for q in queries}
        reranked={q['id']:prior['trace'][q['id']]['cross_encoder_top50'] for q in queries}
    else:pools,reranked=rank_candidates(units,[query_input(q) for q in queries],ROOT/'.model-cache/mps')
    rows,trace=build_manifests(fixture,result,queries,pools,reranked)
    body=''.join(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n' for row in rows)
    manifest={'status':'complete','query_count':len(queries),'row_count':len(rows),'selection_seed':SEED,
        'selected_query_ids':[q['id'] for q in queries],'selected_families':dict(__import__('collections').Counter(q['family'] for q in queries)),
        'manifest_sha256':hashlib.sha256(body.encode()).hexdigest(),'fixture_sha256':sha256(args.fixture),'retrieval_result_sha256':sha256(args.results),
        'prompt_sha256':sha256(PROMPT),'trace':trace,'models':{'dense':'all-MiniLM-L6-v2 FP32 MPS max_seq_length256','cross_encoder':'ms-marco-MiniLM-L6-v2 FP32 MPS max_length512'},
        'ranking_execution':'Reused immutable rank traces; no model inference' if args.reuse_ranking_manifest else 'Local model inference during this run',
        'reused_ranking_manifest_sha256':inputs.get(args.reuse_ranking_manifest),
        'model_artifact_sha256':{str(p.relative_to(ROOT/'.model-cache/mps')):value for p,value in artifacts.items()},
        'candidate_units':{'count':len(units),'types':dict(__import__('collections').Counter(u['id'].split(':',1)[0] for u in units)),
            'deduplication':'Distinct typed item IDs; assertion chunks include their passages and passages are independently rankable. Top5 units selected before flattening; repeated typed context IDs collapse on first occurrence, without backfill.'},
        'selection':'A dense all raw assertion chunks, independent passages, and notice records top5; C reorder same A top50 then top5; B question-regex entity allversions/notices; D/E exact recorded top5 rows. Gold is added after context assembly.'}
    if any(sha256(path)!=expected for path,expected in inputs.items()):raise RuntimeError('Fixture, retrieval results or prompt changed during context assembly.')
    if any(sha256(path)!=expected for path,expected in artifacts.items()):raise RuntimeError('Local model artifact changed during context assembly.')
    receipt=run_context.write_bytes(args.output,body.encode())
    manifest['jsonl_write_provenance']=receipt['provenance']
    run_context.write_json(args.output.with_suffix('.manifest.json'),manifest)
    print(json.dumps({'output':str(args.output),'rows':len(rows),'sha256':manifest['manifest_sha256']}))


if __name__=='__main__':main()
