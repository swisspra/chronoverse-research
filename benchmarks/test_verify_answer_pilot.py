import hashlib
import json
import pytest

from benchmarks.answer_experiment import prepare
from benchmarks.verify_answer_pilot import verify


def sample():
    prompt='{question} {recipient_id} {valid_at} {known_at} {received_by} {context}'
    ph=hashlib.sha256(prompt.encode()).hexdigest()
    rows=[dict(query_id='q1',arm=a,question='Value?',recipient_id='red',valid_at='2026-01-01',known_at='2026-01-02',received_by='2026-01-02',context=[],gold_support_ids=[],expected_answers=[],visible_ids=[],answerable=False,prompt_sha256=ph) for a in 'ABCDE']
    raw=('\n'.join(json.dumps(row) for row in rows)+'\n').encode()
    requests,estimate=prepare(rows,prompt,'vertex_ai/gemini-3.8-flash',max_input_tokens=8192,long_max_input_tokens=16384,max_completion_tokens=1024)
    result=dict(status='complete',estimate=estimate,manifest_sha256=hashlib.sha256(raw).hexdigest(),prompt_sha256=ph,actual_response_model='vertex_ai/gemini-3.8-flash',expected_response_model='vertex_ai/gemini-3.8-flash',requests={})
    for request in requests:
        r={k:v for k,v in request.items() if k!='body'}
        r.update(status='complete',finish_reason='stop',raw_answer='INSUFFICIENT EVIDENCE',returned_model='vertex_ai/gemini-3.8-flash',seconds=1,usage=dict(prompt_tokens=20,completion_tokens=10,total_tokens=30))
        result['requests'][r['id']]=r
    options=dict(expected_manifest_sha256=result['manifest_sha256'],expected_prompt_sha256=ph,query_count=1)
    return raw,prompt.encode(),result,options


def test_valid_and_transport_format_diagnostics_keep_failures():
    raw,prompt,result,options=sample();rs=list(result['requests'].values())
    rs[0].update(status='truncated_or_invalid',finish_reason='length',raw_answer='')
    rs[1]['raw_answer']=''
    rs[2]['raw_answer']='Uncited answer'
    audit=verify(raw,prompt,result,**options)
    assert audit['status']=='passed'
    assert audit['totals']['length_finish_count']==1
    assert audit['totals']['empty_stop_completions']==1
    assert audit['totals']['citation_parse_error']==2
    assert audit['totals']['nonempty_nonabstained_completions']==1


@pytest.mark.parametrize('corruption', ['missing','duplicate_slot','usage_missing','usage_nan','usage_bool','usage_over','reservation','model','guard','pending','status_finish','manifest','prompt','request_id'])
def test_corruption_rejected(corruption):
    raw,prompt,result,options=sample();key=next(iter(result['requests']));r=result['requests'][key]
    if corruption=='missing':result['requests'].pop(key)
    elif corruption=='duplicate_slot':list(result['requests'].values())[1]['arm']=r['arm']
    elif corruption=='usage_missing':r['usage'].pop('completion_tokens')
    elif corruption=='usage_nan':r['usage']['prompt_tokens']=float('nan')
    elif corruption=='usage_bool':r['usage']['prompt_tokens']=True
    elif corruption=='usage_over':r['usage']['completion_tokens']=1025
    elif corruption=='reservation':r['output_reservation']=2048
    elif corruption=='model':r['returned_model']='another-model'
    elif corruption=='guard':r['budget_breach']=True
    elif corruption=='pending':r['status']='pending'
    elif corruption=='status_finish':r['finish_reason']='length'
    elif corruption=='manifest':result['manifest_sha256']='0'*64
    elif corruption=='prompt':prompt+=b'changed'
    elif corruption=='request_id':result['requests']['bad']=result['requests'].pop(key)
    with pytest.raises(ValueError):verify(raw,prompt,result,**options)
