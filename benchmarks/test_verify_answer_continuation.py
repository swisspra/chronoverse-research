import copy
import json
import pytest
from benchmarks.test_verify_answer_pilot import sample
from benchmarks.verify_answer_pilot import sha
from benchmarks.verify_answer_continuation import verify_union,verify_bindings,UNCERTAIN_ID


def fixture():
    raw,prompt,union,options=sample()
    original_records=dict(list(union['requests'].items())[:7]);uncertain_id=list(original_records)[-1]
    uncertain=original_records[uncertain_id]
    for key in ('raw_answer','returned_model','finish_reason','usage'):uncertain.pop(key)
    uncertain.update(status='uncertain',error_type='TimeoutError',http_status=None)
    original={'requests':original_records,'estimate':union['estimate'],'actual_response_model':union['actual_response_model']}
    original_raw=json.dumps(original).encode();original_hash=sha(original_raw)
    continuation={k:copy.deepcopy(v) for k,v in union.items() if k!='requests'}
    continuation.update(status='complete',requests=copy.deepcopy(dict(list(union['requests'].items())[7:])),original_checkpoint_sha256=original_hash)
    union.update(status='completed_plan_with_uncertainty',original_checkpoint_sha256=original_hash)
    subset={**union['estimate'],'requests':8,'input_token_reservation':sum(r['input_reservation'] for r in continuation['requests'].values()),'output_token_reservation':8*1024}
    continuation['continuation_estimate']=copy.deepcopy(subset);union['continuation_estimate']=copy.deepcopy(subset)
    options.update(expected_original_sha256=original_hash,original_count=7,uncertain_id=uncertain_id)
    return raw,prompt,original_raw,continuation,union,options


def test_accounted_plan_is_not_successful_terminal_run():
    args=fixture();audit=verify_union(*args[:5],**args[5])
    assert audit['status']=='completed_plan_with_uncertainty'
    assert audit['terminal_responses']==14 and audit['uncertain_outcomes']==1
    assert audit['unknown_usage_slots']==1
    assert audit['continuation_slots']==8


@pytest.mark.parametrize('change',['original_bytes','original_record','overlap','missing','second_uncertain','usage_over','missing_usage','model','caps','manifest','order','pretend_complete','timeout_usage','subset_budget','usage_guard'])
def test_corruption_rejected(change):
    raw,prompt,original_raw,continuation,union,options=fixture()
    key=next(iter(continuation['requests']));r=continuation['requests'][key]
    if change=='original_bytes':original_raw+=b' '
    elif change=='original_record':union['requests'][next(iter(union['requests']))]['seconds']=200
    elif change=='overlap':continuation['requests'][next(iter(union['requests']))]=copy.deepcopy(next(iter(union['requests'].values())))
    elif change=='missing':continuation['requests'].pop(key);union['requests'].pop(key)
    elif change=='second_uncertain':r['status']='uncertain';union['requests'][key]=copy.deepcopy(r)
    elif change=='usage_over':r['usage']['completion_tokens']=1025;union['requests'][key]=copy.deepcopy(r)
    elif change=='missing_usage':r.pop('usage');union['requests'][key]=copy.deepcopy(r)
    elif change=='model':r['returned_model']='wrong';union['requests'][key]=copy.deepcopy(r)
    elif change=='caps':r['output_reservation']=2048;union['requests'][key]=copy.deepcopy(r)
    elif change=='manifest':union['manifest_sha256']='wrong'
    elif change=='order':continuation['requests']=dict(reversed(list(continuation['requests'].items())))
    elif change=='pretend_complete':union['status']='complete'
    elif change=='timeout_usage':union['requests'][options['uncertain_id']]['usage']={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}
    elif change=='subset_budget':continuation['continuation_estimate']['input_token_reservation']+=1
    elif change=='usage_guard':r['usage_guard_failure']=True;union['requests'][key]=copy.deepcopy(r)
    with pytest.raises(ValueError):verify_union(raw,prompt,original_raw,continuation,union,**options)


@pytest.mark.parametrize('change',[None,'commit','source_digest','original_digest','repair','amendment','continuation_file'])
def test_phase_and_source_bindings(change):
    _,_,original_raw,c,u,_=fixture();original=json.loads(original_raw);original['run_id']='original';original_raw=json.dumps(original).encode()
    for artifact in (c,u):
        artifact.update(original_records_json_sha256=sha(json.dumps(original['requests'],sort_keys=True,ensure_ascii=False).encode()),
            original_source_commit='9ece9b9',repaired_execute_commit='e77c0d7',amendment_commit='009f732',unknown_original_request_id=UNCERTAIN_ID,
            unknown_original_usage=True,original_run_id='original',continuation_run_id='continuation',provenance={'git_commit':'frozen','source_sha256':{'runner.py':'hash'}})
    c['phase']='undispatched_only_continuation';u['phase']='original_plus_undispatched_continuation'
    if change=='commit':u['provenance']={**u['provenance'],'git_commit':'changed'}
    elif change=='source_digest':u['provenance']={**u['provenance'],'source_sha256':{'runner.py':'different'}}
    elif change=='original_digest':c['original_records_json_sha256']='wrong'
    elif change=='repair':u['repaired_execute_commit']='wrong'
    elif change=='amendment':u['amendment_commit']='wrong'
    cr=json.dumps(c).encode();u['continuation_result_sha256']=sha(cr) if change!='continuation_file' else 'wrong'
    raw={'original':original_raw,'continuation':cr,'union':json.dumps(u).encode()}
    if change:
        with pytest.raises(ValueError):verify_bindings(raw)
    else:assert verify_bindings(raw)==(c,u)
