"""Audit repository-authored target support against a separately authored reference.

Eligibility composes by assertion identity. This checks each scenario's entity
subledger; distractor ranking is intentionally outside this reference audit.
"""
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from benchmarks.reference_v3 import project

ROOT=Path(__file__).resolve().parents[1]


def validate(fixture):
    entities=defaultdict(list);events=defaultdict(list);receipts=defaultdict(list)
    for a in fixture['assertions']:entities[a['subject']].append(a)
    for e in fixture['events']:events[e['assertion_id']].append(e)
    for r in fixture['receipts']:receipts[r['item_id']].append(r)
    mismatches=[];checked=0;gold=[]
    for q in fixture['queries']:
        if q['split']=='compatibility':continue
        assertions=entities[q['entity']];known_ids=[];ev=[]
        for a in assertions:
            known_ids.append(a['id'])
            known_ids.extend(e.get('id',f"{a['id']}-e{i}") for i,e in enumerate(a['evidence'],1))
            ev.extend(events[a['id']])
        known_ids.extend(e['id'] for e in ev)
        ledger={'assertions':assertions,'events':ev,'receipts':[r for item in known_ids for r in receipts[item]]}
        p=project(ledger,q)
        relevant={a['id'] for a in assertions if a['predicate']=='reported capacity'}
        claims={a['id'] for a in p['assertions'] if a['id'] in relevant}
        passages={e['id'] for e in p['evidence'] if e['parent_id'] in relevant}
        notices={e['id'] for e in p['events']}
        if q['kind']=='assertion':
            expected={'assertion:'+x for x in q['gold_assertion_ids']}
            actual={'assertion:'+x for x in claims}
        elif q['kind']=='evidence':
            expected={'evidence:'+x for x in q['gold_evidence_ids']}
            actual={'evidence:'+x for x in passages}
        else:
            expected={'event:'+x for x in q['gold_event_ids']}
            actual={'event:'+x for x in notices}
        if actual!=expected:mismatches.append({'query_id':q['id'],'expected':sorted(expected),'reference':sorted(actual)})
        gold.append({'query_id':q['id'],'reference_support':sorted(actual)})
        checked+=1
    return {'checked':checked,'mismatches':mismatches,'reference_derived_support':gold,
            'method':'Per-entity eligibility audit; repository-authored relevance predicate is reported capacity. No ranking gold invented from globally visible distractors.',
            'reference_sha256':hashlib.sha256((ROOT/'benchmarks/reference_v3.py').read_bytes()).hexdigest()}

if __name__=='__main__':
    fixture=json.loads(gzip.decompress((ROOT/'benchmarks/data/delivery-v3.json.gz').read_bytes()))
    result=validate(fixture)
    print(json.dumps({k:v for k,v in result.items() if k!='reference_derived_support'},indent=2))
    if result['mismatches']:raise SystemExit(1)
