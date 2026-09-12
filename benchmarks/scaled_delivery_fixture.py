"""Deterministic scenario generator. No Store, retriever, scoring or model imports."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260912
FAMILIES = {'delayed_correction':75, 'delayed_retraction':50,
            'correction_before_replacement':50, 'historical_event_receipt':50,
            'time_only_near_duplicate':75, 'orphan_evidence':25,
            'boundary_exact':50, 'cross_recipient_isolation':50, 'no_support':75}
RECIPIENTS = [f'recipient-{i}' for i in range(10)]


def stamp(base, days=0, micros=0):
    return (base+timedelta(days=days,microseconds=micros)).isoformat(timespec='microseconds').replace('+00:00','Z')


def build(seed=SEED):
    rng=random.Random(seed)
    fixture={'version':'delivery-v3', 'seed':seed, 'assertions':[], 'events':[], 'receipts':[], 'queries':[],
             'protocol':'benchmarks/SPEC-TRI-TEMPORAL.md',
             'family_targets':FAMILIES, 'recipients':RECIPIENTS,
             'authoring':'Scenario-template gold authored in this repository; separate specification-only validation is recorded separately, never assumed.',
             'split_rule':'Distinct entity and scenario-family variant across DEV/TEST; parent mechanisms are deliberately shared and reported.',
             'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for split, counts in [('test',FAMILIES),('dev',{key:12 for key in FAMILIES})]:
        serial=0
        for family,count in counts.items():
            for case in range(count):
                serial+=1
                entity=f'{split.title()} monitoring station {serial:04d}'
                uid=f'{split}-{serial:04d}'
                actor=RECIPIENTS[serial%len(RECIPIENTS)]
                # Dates vary by scenario to avoid a single constant clock shortcut.
                base=datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=rng.randrange(200))
                old,new=uid+'-a',uid+'-b'
                def assertion(aid,value,start=0,end=None,recorded=0):
                    return {'id':aid,'subject':entity,'predicate':'reported capacity','object':str(value),
                            'summary':f'{entity} reported capacity is {value} units.',
                            'world':'main','plane':'report','perspective':'general',
                            'valid_from':stamp(base,start),'valid_to':stamp(base,end) if end is not None else None,
                            'recorded_at':stamp(base,recorded),
                            'evidence':[{'title':f'{entity} capacity report','text':f'{entity} reported capacity is {value} units.',
                                         'recorded_at':stamp(base,recorded),'synthetic':True}]}
                value=20+(serial%70)
                first=assertion(old,value)
                second=assertion(new,value+5,start=0,recorded=2)
                fixture['assertions'].extend([first,second])
                event={'id':uid+'-notice','assertion_id':old,'type':'correct','effective_at':stamp(base,1),
                       'recorded_at':stamp(base,3),'reason':f'{entity}: original capacity report corrected.',
                       'source':f'Synthetic station {serial} notice','replacement_id':new}
                if family=='delayed_retraction':
                    event['type']='retract';event.pop('replacement_id')
                if family=='historical_event_receipt': event['type']='supersede'
                # All scenarios include a real lifecycle event; a late receipt can keep it invisible.
                fixture['events'].append(event)
                def receive(kind,item,recipient,day,logged=None,micros=0):
                    fixture['receipts'].append({'id':f'r-{len(fixture["receipts"]):07d}',
                        'recipient_id':recipient,'item_type':kind,'item_id':item,
                        'received_at':stamp(base,day,micros), 'recorded_at':stamp(base,day if logged is None else logged,micros)})
                # Broadly delivered, adjacent distractors remain genuine retrieval competition.
                for j in range(10):
                    distractor=assertion(f'{uid}-d{j}',value+j+20,start=-20,end=-10) if j<3 else assertion(f'{uid}-d{j}',value+j+20)
                    if j>=3:
                        distractor['predicate']='forecast capacity' if j%2 else 'reported throughput'
                        distractor['summary']=f'{entity} {distractor["predicate"]} is {value+j+20} units.'
                        distractor['evidence'][0]['text']=distractor['summary']
                    fixture['assertions'].append(distractor)
                    for recipient in RECIPIENTS:
                        receive('assertion',distractor['id'],recipient,0)
                        receive('evidence',distractor['id']+'-e1',recipient,0)
                for recipient in RECIPIENTS:
                    receive('assertion',old,recipient,0)
                    receive('evidence',old+'-e1',recipient,0)
                    receive('assertion',new,recipient,2)
                    receive('evidence',new+'-e1',recipient,2)
                    receive('event',event['id'],recipient,7)
                scope={'valid_at':stamp(base,4),'known_at':stamp(base,10),'received_by':stamp(base,4),
                       'world':'main','plane':'report','perspective':'general'}
                gold=[old,new];evidence=[old+'-e1',new+'-e1'];events=[];kind='assertion'
                expected=[str(value),str(value+5)]
                # Replace only this recipient's scenario receipts. Other actors remain controls.
                own=lambda r: r['recipient_id']==actor and r['item_id'] in {old,new,old+'-e1',new+'-e1',event['id']}
                own_rows=[r for r in fixture['receipts'] if own(r)]
                def delay(item,day,logged=None,micros=0):
                    for r in own_rows:
                        if r['item_id']==item:
                            r['received_at']=stamp(base,day,micros);r['recorded_at']=stamp(base,day if logged is None else logged,micros)
                if family in ('delayed_correction','delayed_retraction'):
                    delay(new,6);delay(new+'-e1',6)
                    gold=[old];evidence=[old+'-e1'];expected=[str(value)]
                elif family=='correction_before_replacement':
                    delay(event['id'],3);delay(new,6);delay(new+'-e1',6)
                    gold=[];evidence=[];events=[event['id']];kind='event';expected=['corrected']
                elif family=='time_only_near_duplicate':
                    # Retrieval text is byte-identical. Only validity separates the versions.
                    second['object']=first['object'];second['summary']=first['summary']
                    second['evidence'][0]['text']=first['evidence'][0]['text']
                    first['valid_to']=stamp(base,1);second['valid_from']=stamp(base,1)
                    gold=[new];evidence=[new+'-e1'];expected=[str(value)]
                elif family=='orphan_evidence':
                    delay(old,6);delay(new,6);delay(new+'-e1',6)
                    gold=[];evidence=[old+'-e1'];kind='evidence';expected=[str(value)]
                elif family=='boundary_exact':
                    # Distinct semantic variants exercise inclusive and exclusive boundaries.
                    variant=case%4
                    delay(event['id'],3)
                    if variant==0:
                        scope.update(received_by=stamp(base,3,micros=-1));gold=[old,new];evidence=[old+'-e1',new+'-e1']
                    elif variant==1:
                        scope.update(received_by=stamp(base,3));gold=[new];evidence=[new+'-e1'];expected=[str(value+5)]
                    elif variant==2:
                        scope.update(known_at=stamp(base,3,micros=-1));gold=[old,new];evidence=[old+'-e1',new+'-e1']
                    else:
                        scope.update(known_at=stamp(base,3));gold=[new];evidence=[new+'-e1'];expected=[str(value+5)]
                elif family=='cross_recipient_isolation':
                    # Receipt log knowledge differs while physical delivery time is equal.
                    delay(event['id'],3,logged=8 if case%2 else 3)
                    scope['known_at']=stamp(base,5)
                    if case%2==0: gold=[new];evidence=[new+'-e1'];expected=[str(value+5)]
                elif family=='no_support':
                    delay(old,6);delay(old+'-e1',6);delay(new,6);delay(new+'-e1',6)
                    gold=[];evidence=[];expected=[]
                question=f'Which capacity values were reported for {entity} in the available reports?'
                if kind=='event':question=f'Which correction notice for {entity} is available, and when is it effective?'
                elif kind=='evidence':question=f'What capacity does the available source passage for {entity} report?'
                # Variant names differ across splits; mechanism overlap is expressly disclosed.
                scenario_family=f'{split}:{family}:variant-{case%4}'
                fixture['queries'].append({'id':uid,'split':split,'family':family,'scenario_family':scenario_family,
                    'cluster_id':uid,'entity':entity,'kind':kind,'recipient_id':actor,'query':question,'scope':scope,
                    'gold_assertion_ids':gold,'gold_evidence_ids':evidence,'gold_event_ids':events,'expected_answers':expected})
    legacy=ROOT/'benchmarks/data/delivery-v1.json'
    if legacy.exists():
        old=json.loads(legacy.read_text())
        fixture['assertions'].extend(old['assertions']);fixture['events'].extend(old['events'])
        fixture['receipts'].extend({**r,'id':'legacy-'+r['id']} for r in old['receipts'])
        fixture['queries'].extend({**q,'split':'compatibility','cluster_id':'legacy-'+q['id'],
                                   'scenario_family':'compatibility:'+q['family'],'kind':'assertion'} for q in old['queries'])
        fixture['compatibility_sha256']=hashlib.sha256(legacy.read_bytes()).hexdigest()
    fixture['counts']={key:len(fixture[key]) for key in ('assertions','events','receipts','queries')}
    fixture['split_counts']=dict(Counter(q['split'] for q in fixture['queries']))
    return fixture


def encoded(fixture):
    return (json.dumps(fixture,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'benchmarks/data/delivery-v3.json');p.add_argument('--seed',type=int,default=SEED)
    args=p.parse_args();content=encoded(build(args.seed))
    if args.output.exists() and args.output.read_bytes()!=content:
        raise SystemExit('Refusing to overwrite a different frozen fixture; choose a new version/path.')
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes(content)
    print(json.dumps({'path':str(args.output),'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}))

if __name__=='__main__':main()
