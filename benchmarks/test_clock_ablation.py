"""Boundary and label isolation tests for a fixed candidate-pool ablation."""
from copy import deepcopy
import pytest
from benchmarks.answer_contexts import candidate_inventory, query_input
from benchmarks.answer_experiment import PROMPT, prepare
from benchmarks.clock_ablation import MODES, project_units
from benchmarks.test_answer_contexts import fixture,query


def test_dropped_receipt_clock_exposes_delivered_lifecycle_difference():
    f=fixture();q=query_input(query());pool=['assertion:old','event:notice','evidence:old-e1']
    full,ids=project_units(f,q,pool,'FULL');assert ids==['assertion:old']
    _,ids=project_units(f,q,pool,'VK');assert ids==['event:notice','evidence:old-e1']
    q['scope']['received_by']='2025-01-09'
    _,ids=project_units(f,q,pool,'FULL');assert ids==['event:notice']
    # Equality is included for both the notice's receipt and receipt-log cutoff.
    q['scope']['known_at']='2025-01-09'
    assert project_units(f,q,pool,'FULL')[1]==['event:notice']


def test_known_and_valid_ablation_keep_raw_passage_and_notice_semantics():
    f=fixture();q=query_input(query());a=f['assertions'][1]
    a['recorded_at']='2025-01-11';a['valid_from']='2025-01-01';a['evidence'][0]['recorded_at']='2025-01-12'
    pool=['assertion:new','evidence:new-e1']
    assert project_units(f,q,pool,'VK')[1]==[]
    assert project_units(f,q,pool,'V')[1]==pool
    a['valid_from']='2025-01-06'
    # Standalone evidence inherits the original interval, not lifecycle state.
    assert project_units(f,q,pool,'V')[1]==[]
    assert project_units(f,q,pool,'NONE')[1]==pool
    a['valid_from']='2025-01-05';a['valid_to']='2025-01-05'
    assert project_units(f,q,pool,'V')[1]==[]


def test_orphan_evidence_interval_ignores_parent_receipt_recording_and_lifecycle():
    f=fixture();q=query_input(query());parent=f['assertions'][0]
    parent['recorded_at']='2025-01-11'
    f['receipts']=[{'recipient_id':'R','item_type':'evidence','item_id':'old-e1','received_at':'2025-01-05T07:00:00+07:00','recorded_at':'2025-01-05T00:00:00Z'},
        {'recipient_id':'R','item_type':'event','item_id':'notice','received_at':'2025-01-02','recorded_at':'2025-01-02'}]
    q['scope']['known_at']='2025-01-05T00:00:00Z'
    pool=['assertion:old','evidence:old-e1','event:notice']
    assert project_units(f,q,pool,'FULL')[1]==['evidence:old-e1','event:notice']
    parent['valid_to']='2025-01-05T07:00:00+07:00'
    assert project_units(f,q,pool,'FULL')[1]==['event:notice']


def test_non_lifecycle_event_does_not_retire_claim():
    f=fixture();q=query_input(query());f['events'][0]['type']='annotation'
    assert project_units(f,q,['assertion:old'],'VK')[1]==['assertion:old']


def test_clock_contexts_never_use_gold_and_do_not_reattach_hidden_children():
    f=fixture();q=query_input(query());pool=['assertion:old','evidence:old-e1','event:notice']
    baseline={mode:project_units(f,q,pool,mode) for mode in MODES}
    poisoned=deepcopy(f);poisoned['queries']=[{'gold_assertion_ids':['SECRET'],'expected_answers':['SECRET']}]
    assert baseline=={mode:project_units(poisoned,q,pool,mode) for mode in MODES}
    assert [c['id'] for c in baseline['FULL'][0]]==['assertion:old']
    notice=next(c['text'] for c in baseline['NONE'][0] if c['id']=='event:notice')
    assert '22' not in notice


def test_four_arm_transport_requires_exact_declared_arms():
    from benchmarks.test_answer_experiment import rows
    source=rows()[0];data=[{**source,'arm':mode} for mode in MODES]
    requests,estimate=prepare(data,PROMPT.read_text(),'fixed-model',max_input_tokens=10000,long_max_input_tokens=10000,max_completion_tokens=1024,arms=MODES)
    assert len(requests)==12 and estimate['arms']==list(MODES)
    assert len({r['body']['messages'][0]['content'] for r in requests})==1
    with pytest.raises(ValueError,match='declared arms'):
        prepare(data[:-1],PROMPT.read_text(),'fixed-model',max_input_tokens=10000,long_max_input_tokens=10000,max_completion_tokens=1024,arms=MODES)
