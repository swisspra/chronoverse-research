"""Offline continuation tests: no provider calls and no inspection of pilot answers."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from benchmarks.answer_experiment import prepare


def driver():
    assert importlib.util.find_spec('benchmarks.answer_continuation') is not None, 'Continuation driver is not implemented'
    from benchmarks import answer_continuation
    return answer_continuation


def sample(monkeypatch):
    m=driver();template='{question}\n{recipient_id}\n{valid_at}\n{known_at}\n{received_by}\n{context}'
    prompt=template.encode();rows=[]
    for i in range(50):
        for arm in 'ABCDE':
            rows.append(dict(query_id=f'test-{i:04}',arm=arm,question='Question',recipient_id='r',valid_at='v',known_at='k',received_by='r',context=[],gold_support_ids=[],expected_answers=[],prompt_sha256=hashlib.sha256(prompt).hexdigest()))
    raw=('\n'.join(json.dumps(r) for r in rows)+'\n').encode()
    requests,estimate=prepare(rows,template,m.MODEL,max_input_tokens=8192,long_max_input_tokens=16384,max_completion_tokens=1024)
    estimate.update(usd_reservation=None,pricing='Proxy pricing unknown; no USD estimate claimed')
    records={}
    for i,r in enumerate(requests[:647]):
        x={k:v for k,v in r.items() if k!='body'}
        if i==646:x.update(status='uncertain',error_type='TimeoutError',http_status=None,seconds=90.1)
        else:x.update(status='complete' if i<533 else 'truncated_or_invalid',finish_reason='stop' if i<533 else 'length',returned_model=m.MODEL,usage={'prompt_tokens':10,'completion_tokens':2,'total_tokens':12},seconds=1.0,raw_answer='opaque fixture',scoring={'do_not_modify':i})
        records[r['id']]=x
    state=dict(run_id=m.ORIGINAL_RUN_ID,requests=records,estimate=estimate,actual_response_model=m.MODEL)
    original=json.dumps(state,ensure_ascii=False).encode()
    for name,value in [('ORIGINAL_SHA',hashlib.sha256(original).hexdigest()),('MANIFEST_SHA',hashlib.sha256(raw).hexdigest()),('PROMPT_SHA',hashlib.sha256(prompt).hexdigest()),('UNCERTAIN_ID',requests[646]['id']),('WHOLE_INPUT',estimate['input_token_reservation'])]:monkeypatch.setattr(m,name,value)
    return m,original,raw,prompt,requests


def test_preserves_prefix_and_never_schedules_attempted_timeout(monkeypatch):
    m,original,raw,prompt,requests=sample(monkeypatch);plan=m.build_plan(original,raw,prompt)
    assert len(plan['remaining'])==103
    assert [r['id'] for r in plan['remaining']]==[r['id'] for r in requests[647:]]
    assert m.UNCERTAIN_ID not in {r['id'] for r in plan['remaining']}
    assert plan['original']['requests']==json.loads(original)['requests']


@pytest.mark.parametrize('change',['hash','reorder','duplicate_slot','usage','nan','model','guard','second_timeout','estimate'])
def test_rejects_modified_or_guarded_original_before_dispatch(monkeypatch,change):
    m,original,raw,prompt,_=sample(monkeypatch);state=json.loads(original);ids=list(state['requests']);r=state['requests'][ids[0]]
    if change=='hash':original+=b' '
    else:
        if change=='reorder':state['requests']={k:state['requests'][k] for k in list(reversed(ids))}
        if change=='duplicate_slot':r['repeat']=2
        if change=='usage':r['usage']['prompt_tokens']=999999
        if change=='nan':r['usage']['total_tokens']=float('nan')
        if change=='model':r['returned_model']='wrong'
        if change=='guard':r['budget_breach']=True
        if change=='second_timeout':r['status']='uncertain'
        if change=='estimate':state['estimate']['requests']=749
        original=json.dumps(state).encode();monkeypatch.setattr(m,'ORIGINAL_SHA',hashlib.sha256(original).hexdigest())
    with pytest.raises(ValueError):m.build_plan(original,raw,prompt)


def test_source_inputs_must_match_captured_hashes(monkeypatch):
    m,original,raw,prompt,_=sample(monkeypatch)
    for mr,pr in [(raw+b' ',prompt),(raw,prompt+b' ')]:
        with pytest.raises(ValueError):m.build_plan(original,mr,pr)


def completed_state(plan,m):
    records={}
    for request in plan['remaining']:
        row={k:v for k,v in request.items() if k!='body'}
        row.update(status='complete',finish_reason='stop',raw_answer='opaque new fixture',seconds=1,returned_model=m.MODEL,usage=dict(prompt_tokens=10,completion_tokens=2,total_tokens=12))
        records[row['id']]=row
    return dict(run_id='new-repaired-source-run',actual_response_model=m.MODEL,requests=records)


def test_union_preserves_every_original_json_value_and_whole_reservation(monkeypatch):
    m,original,raw,prompt,_=sample(monkeypatch);plan=m.build_plan(original,raw,prompt)
    continuation,union=m.artifacts(plan,completed_state(plan,m))
    assert union['status']=='completed_plan_with_uncertainty'
    assert continuation['status']=='complete' and len(continuation['requests'])==103
    assert len(union['requests'])==750
    assert {k:union['requests'][k] for k in plan['original']['requests']}==json.loads(original)['requests']
    assert union['estimate']==json.loads(original)['estimate']
    assert union['requests'][m.UNCERTAIN_ID]['status']=='uncertain'
    assert 'usage' not in union['requests'][m.UNCERTAIN_ID]


@pytest.mark.parametrize('change',['missing','extra','uncertain','usage','reorder'])
def test_union_rejects_partial_overlap_and_invalid_continuation(monkeypatch,change):
    m,original,raw,prompt,_=sample(monkeypatch);plan=m.build_plan(original,raw,prompt);state=completed_state(plan,m);ids=list(state['requests'])
    if change=='missing':state['requests'].pop(ids[-1])
    if change=='extra':state['requests'][m.UNCERTAIN_ID]=plan['original']['requests'][m.UNCERTAIN_ID]
    if change=='uncertain':state['requests'][ids[0]]['status']='uncertain'
    if change=='usage':state['requests'][ids[0]]['usage']['completion_tokens']=1025
    if change=='reorder':state['requests']={k:state['requests'][k] for k in reversed(ids)}
    with pytest.raises(ValueError):m.artifacts(plan,state)


@pytest.mark.parametrize('failure',['timeout','missing_usage','nonnumeric_usage','total_only_excess','prompt_excess','wrong_model'])
def test_one_new_failure_stops_and_preserves_known_provider_observation(monkeypatch,tmp_path,failure):
    m,original,raw,prompt,_=sample(monkeypatch);plan=m.build_plan(original,raw,prompt)
    for row in plan['rows']:row.update(visible_ids=[],answerable=False)
    monkeypatch.setattr(m,'verify_endpoint_identity',lambda plan,url:None)
    calls=[]
    usage=dict(prompt_tokens=10,completion_tokens=2,total_tokens=12)
    if failure=='missing_usage':usage=None
    if failure=='nonnumeric_usage':usage['prompt_tokens']='10'
    if failure=='total_only_excess':usage['total_tokens']=999999
    if failure=='prompt_excess':usage['prompt_tokens']=999999
    def send(endpoint,key,body,timeout):
        calls.append(body)
        if failure=='timeout':raise TimeoutError()
        return dict(id='observed-provider-response',model='wrong' if failure=='wrong_model' else m.MODEL,
            choices=[dict(finish_reason='stop',message=dict(content='INSUFFICIENT EVIDENCE'))],usage=usage)
    path=tmp_path/'new.json'
    with pytest.raises(RuntimeError):m.dispatch(plan,base_url='https://example.test/v1',key='offline',checkpoint=path,send=send)
    saved=json.loads(path.read_text());assert len(saved['requests'])==len(calls)==1
    record=next(iter(saved['requests'].values()))
    if failure!='timeout':
        assert record['usage']==usage
        assert record['raw_answer']=='INSUFFICIENT EVIDENCE'
        assert record['response_id']=='observed-provider-response'
    with pytest.raises(ValueError):m.dispatch(plan,base_url='https://example.test/v1',key='offline',checkpoint=path,send=send)
    assert len(calls)==1
    assert json.loads(original)['requests']==plan['original']['requests']


def test_success_dispatch_uses_exact_suffix_bodies_and_subset_budget(monkeypatch,tmp_path):
    m,original,raw,prompt,requests=sample(monkeypatch);plan=m.build_plan(original,raw,prompt)
    for row in plan['rows']:row.update(visible_ids=[],answerable=False)
    monkeypatch.setattr(m,'verify_endpoint_identity',lambda plan,url:None)
    bodies=[]
    def send(endpoint,key,body,timeout):
        bodies.append(copy.deepcopy(body))
        return dict(id='offline',model=m.MODEL,choices=[dict(finish_reason='stop',message=dict(content='INSUFFICIENT EVIDENCE'))],usage=dict(prompt_tokens=10,completion_tokens=2,total_tokens=12))
    state=m.dispatch(plan,base_url='https://example.test/v1',key='offline',checkpoint=tmp_path/'new.json',send=send)
    assert bodies==[r['body'] for r in requests[647:]]
    assert state['estimate']['input_token_reservation']==sum(r['input_reservation'] for r in requests[647:])
    assert state['estimate']['output_token_reservation']==105472
    assert m.artifacts(plan,state)[1]['status']=='completed_plan_with_uncertainty'
