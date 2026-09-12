"""Gold-independent context assembly and recipient-aware citation audit."""
from copy import deepcopy

from benchmarks.answer_contexts import ROOT, build_manifests, candidate_inventory, catalog, entity_context, load, pilot_queries, query_input, scoring_metadata, serialize_context


def fixture():
    def assertion(id,value):return {'id':id,'subject':'Test monitoring station 0001','predicate':'capacity','object':value,
        'summary':value,'world':'main','plane':'report','perspective':'general','valid_from':'2025-01-01','valid_to':None,
        'recorded_at':'2025-01-01','evidence':[{'text':value,'recorded_at':'2025-01-01'}]}
    assertions=[assertion('old','21'),assertion('new','22')]+[dict(assertion('d'+str(i),'99'),subject='Other station') for i in range(48)]
    event={'id':'notice','assertion_id':'old','type':'correct','effective_at':'2025-01-01','recorded_at':'2025-01-02','replacement_id':'new'}
    receipts=[{'recipient_id':'R','item_type':'assertion','item_id':'old','received_at':'2025-01-01','recorded_at':'2025-01-01'},
              {'recipient_id':'R','item_type':'event','item_id':'notice','received_at':'2025-01-09','recorded_at':'2025-01-09'}]
    return {'assertions':assertions,'events':[event],'receipts':receipts}


def query():return {'id':'q','query':'Which capacity for Test monitoring station 0001?','recipient_id':'R','scope':{'valid_at':'2025-01-05','known_at':'2025-01-10','received_by':'2025-01-05'},
    'expected_answers':['21'],'gold_assertion_ids':['old'],'gold_evidence_ids':['old-e1'],'gold_event_ids':[],'family':'delayed_correction','kind':'assertion'}


def test_contexts_ignore_poisoned_gold_and_preserve_actual_D_E():
    f=fixture();a,_,_,_=catalog(f);q=query();pool=[r['id'] for r in candidate_inventory(f)][:50]
    result={'methods':{'Filter after projection':{'per_query':{'q':{'results':[]}}},
                       'Delivery explicit item view':{'per_query':{'q':{'results':[dict(a[0],evidence=[],events=[])]}}}}}
    before,_=build_manifests(f,result,[q],{'q':pool},{'q':list(reversed(pool))})
    poisoned=deepcopy(q);poisoned.update(expected_answers=['SECRET'],gold_assertion_ids=['SECRET'],gold_evidence_ids=['SECRET-e1'],entity='Another station')
    after,_=build_manifests(f,result,[poisoned],{'q':pool},{'q':list(reversed(pool))})
    assert [r['context'] for r in before]==[r['context'] for r in after]
    assert before[3]['context']==[]
    assert [r['id'] for r in before[4]['context']]==['assertion:old']
    assert any(r['id']=='event:notice' for r in before[1]['context'])


def test_all_raw_item_types_rank_independently_without_gold_or_replacement_text():
    f=fixture();original=candidate_inventory(f);poisoned=deepcopy(f)
    poisoned['queries']=[dict(query(),expected_answers=['GOLD POISON'])]
    for a in poisoned['assertions']:
        a['gold_assertion_ids']=['GOLD POISON'];a['correct_answer']='GOLD POISON'
        for e in a['evidence']:e['gold_evidence_ids']=['GOLD POISON']
    for event in poisoned['events']:event['expected_answers']=['GOLD POISON']
    assert [(u['id'],u['text']) for u in original]==[(u['id'],u['text']) for u in candidate_inventory(poisoned)]
    by_id={u['id']:u for u in original}
    assert {'assertion:old','evidence:old-e1','event:notice'}<=by_id.keys()
    assert '22' not in by_id['event:notice']['text']
    assert by_id['evidence:old-e1']['rows'][0]['item_type']=='evidence'
    # Rank a standalone notice, passage and its parent together; flatten once per typed ID.
    pool=['event:notice','evidence:old-e1','assertion:old']
    pool.extend(u['id'] for u in original if u['id'] not in pool)
    result={'methods':{name:{'per_query':{'q':{'results':[]}}} for name in ('Filter after projection','Delivery explicit item view')}}
    rows,_=build_manifests(f,result,[query()],{'q':pool[:50]},{'q':pool[:50]})
    ids=[c['id'] for c in rows[0]['context']]
    assert ids[:3]==['event:notice','evidence:old-e1','assertion:old']
    assert ids.count('evidence:old-e1')==1


def test_unreceived_correction_does_not_mark_legitimate_old_claim_stale():
    _,items,owners,receipts=catalog(fixture());q=query()
    early=scoring_metadata(q,items,owners,receipts)
    assert 'assertion:old' not in early['stale_ids'] and 'event:notice' not in early['visible_ids']
    q['scope']['received_by']='2025-01-10'
    later=scoring_metadata(q,items,owners,receipts)
    assert 'assertion:old' in later['stale_ids'] and 'event:notice' in later['visible_ids']


def test_fixed_stratified_pilot_covers_nine_families_and_never_uses_gold():
    f=load(ROOT/'benchmarks/data/delivery-v3.json.gz')
    selected=pilot_queries(f['queries']);assert len(selected)==50 and len({q['family'] for q in selected})==9
    assert len(pilot_queries(f['queries'],500))==500
    poisoned=deepcopy(f['queries'])
    for q in poisoned:q.update(expected_answers=['POISON'],gold_assertion_ids=[],gold_evidence_ids=[],gold_event_ids=[])
    assert [q['id'] for q in pilot_queries(poisoned)]==[q['id'] for q in selected]


def test_support_equivalence_requires_own_received_and_recorded_gold_evidence():
    f=fixture();q=query();_,items,owners,receipts=catalog(f)
    assert scoring_metadata(q,items,owners,receipts)['support_equivalence_groups']==[{'required_id':'assertion:old','acceptable_ids':['assertion:old']}]
    key=('R','evidence:old-e1');receipts[key]=[{'recorded_at':'2025-01-04','received_at':'2025-01-03'}]
    assert scoring_metadata(q,items,owners,receipts)['support_equivalence_groups'][0]['acceptable_ids']==['assertion:old','evidence:old-e1']
    items['evidence:old-e1']['recorded_at']='2025-01-11'
    assert scoring_metadata(q,items,owners,receipts)['support_equivalence_groups'][0]['acceptable_ids']==['assertion:old']
    items['evidence:old-e1']['recorded_at']='2025-01-01';q['gold_assertion_ids']=[]
    # Orphan passage support stays its own ID and does not accept the parent.
    assert scoring_metadata(q,items,owners,receipts)['support_equivalence_groups']==[{'required_id':'evidence:old-e1','acceptable_ids':['evidence:old-e1']}]


def test_retired_parent_does_not_retire_orphan_passage_or_resurrect_claim():
    f=fixture();q=query();_,items,owners,receipts=catalog(f)
    receipts[('R','evidence:old-e1')]=[{'recorded_at':'2025-01-05T00:00:00Z','received_at':'2025-01-05T07:00:00+07:00'}]
    q['scope']['received_by']='2025-01-10T00:00:00Z'
    metadata=scoring_metadata(q,items,owners,receipts)
    assert 'assertion:old' in metadata['stale_ids'] and 'evidence:old-e1' not in metadata['stale_ids']
    assert metadata['support_equivalence_groups']==[{'required_id':'assertion:old','acceptable_ids':[]}]
    q['gold_assertion_ids']=[]
    metadata=scoring_metadata(q,items,owners,receipts)
    assert metadata['support_equivalence_groups']==[{'required_id':'evidence:old-e1','acceptable_ids':['evidence:old-e1']}]
    items['assertion:old']['valid_to']='2025-01-05T07:00:00+07:00'
    assert 'evidence:old-e1' in scoring_metadata(q,items,owners,receipts)['stale_ids']


def test_bounded_receipts_normalize_timezone_at_equality():
    f=fixture();assertions,_,_,receipts=catalog(f);q=query_input(query())
    q['scope']['received_by']='2025-01-05T00:00:00Z';q['scope']['known_at']='2025-01-05T00:00:00Z'
    receipts[('R','assertion:old')]=[{'recorded_at':'2025-01-05T07:00:00+07:00','received_at':'2025-01-05T07:00:00+07:00'}]
    import json
    text=serialize_context([dict(assertions[0],evidence=[])],[],q,receipts,bounded_receipts=True)[0]['text']
    assert len(json.loads(text)['receipts_for_recipient'])==1
