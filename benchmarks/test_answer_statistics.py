"""Independent arithmetic checks; no hosted answers or TEST outputs."""
from copy import deepcopy
import pytest
from benchmarks.answer_statistics import holm,paired,summarize,validate_binding
from benchmarks.test_answer_experiment import rows


def inputs():
    manifest=rows()
    empty=deepcopy(manifest)
    for row in empty:row.update(query_id='empty',family='empty',answerable=False,expected_answers=[],gold_support_ids=[])
    manifest+=empty;records={}
    for row in manifest:
        for repeat in range(3):
            key=f"{row['query_id']}/{row['arm']}/{repeat}"
            records[key]={'query_id':row['query_id'],'arm':row['arm'],'repeat':repeat,'status':'complete','finish_reason':'stop',
                'returned_model':'fixed','raw_answer':'2\n["assertion:x"]' if row['answerable'] else 'INSUFFICIENT EVIDENCE',
                'scoring':{'answer_closed_form_match':False},'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}
    return manifest,records


def test_failed_attempts_remain_accuracy_failures_but_unknown_citation_audits():
    manifest,records=inputs();records['q1/E/1'].update(status='truncated_or_invalid',finish_reason='length')
    del records['empty/E/2']
    result=summarize(manifest,records,'fixed',bootstrap=100,permutations=100)
    e=result['arms']['E']['metrics']
    assert result['planned_requests']==30 and result['recorded_requests']==29
    assert e['closed_form']=={'value':pytest.approx(4/6),'denominator':6}
    assert e['support_recovery']=={'value':pytest.approx(2/3),'denominator':3}
    assert e['citation_leak']=={'value':0,'denominator':4}
    assert e['false_abstention']=={'value':0,'denominator':2}
    assert result['paired_contrasts']['closed_form']['E-A']['query_pairs']==2
    fa=result['paired_contrasts']['false_abstention']['E-A']
    assert fa['query_pairs']==0 and fa['excluded_query_count']==1 and 'p_raw' not in fa
    assert result['arms']['E']['repeat_variation']['closed_form']['sample_variance']==pytest.approx(1/12)
    # Stored score fields are ignored and recalculated from raw answers.
    assert result['arms']['A']['metrics']['closed_form']['value']==1


def test_query_pairing_and_bonferroni_interval_not_repeat_pseudoreplication():
    result=paired([1,0,-1],['x','x','y'],bootstrap=200,permutations=200)
    assert result['query_pairs']==3 and result['difference_E_minus_other']==0
    assert result['bonferroni_ci98_75'][0]<=result['ci95'][0]
    assert result['bonferroni_ci98_75'][1]>=result['ci95'][1]
    assert result['p_raw']==1
    assert paired([],[]) is None
    contrasts={str(i):{'p_raw':p} for i,p in enumerate((.01,.02,.03,.5))};holm(contrasts)
    assert [v['p_holm'] for v in contrasts.values()]==pytest.approx([.04,.06,.06,.5])


def test_actual_model_mismatch_is_not_scored_as_the_requested_model():
    manifest,records=inputs();records['q1/A/0']['returned_model']='other-model'
    result=summarize(manifest,records,'fixed',bootstrap=20,permutations=20)
    assert result['arms']['A']['metrics']['closed_form']['value']==pytest.approx(5/6)
    assert result['actual_response_models']['other-model']==1
    duplicate=deepcopy(records['q1/A/0']);records['duplicate']=duplicate
    with pytest.raises(ValueError,match='duplicate'):summarize(manifest,records,'fixed')


@pytest.mark.parametrize('field,value',[('family','changed'),('answerable',False),('gold_support_ids',['other']),('support_equivalence_groups',[])])
def test_shared_scoring_metadata_cannot_differ_between_arms(field,value):
    manifest,records=inputs();manifest[1][field]=value
    with pytest.raises(ValueError,match='metadata differs'):summarize(manifest,records,'fixed')


def test_strict_manifest_and_prompt_binding_including_partial_exports():
    import hashlib,json
    from benchmarks.answer_experiment import PROMPT
    manifest,_=inputs();raw='\n'.join(json.dumps(r) for r in manifest).encode();prompt=PROMPT.read_bytes()
    captured={'manifest_sha256':hashlib.sha256(raw).hexdigest(),'prompt_sha256':hashlib.sha256(prompt).hexdigest()}
    assert validate_binding(raw,manifest,captured,prompt)['source']=='Final result hashes'
    with pytest.raises(ValueError,match='Missing captured'):validate_binding(raw,manifest,{},prompt)
    assert 'Explicit captured' in validate_binding(raw,manifest,{},prompt,captured)['source']
    with pytest.raises(ValueError,match='manifest hash'):validate_binding(raw+b'\n',manifest,captured,prompt)
    with pytest.raises(ValueError,match='prompt hashes'):validate_binding(raw,manifest,captured,prompt+b'changed')
    with pytest.raises(ValueError,match='manifest hash'):validate_binding(raw,manifest,{**captured,'manifest_sha256':'wrong'},prompt,captured)


def test_arm_token_and_latency_costs_include_invalid_attempt_overhead():
    manifest,records=inputs()
    for i,key in enumerate(('q1/A/0','q1/A/1','q1/A/2','empty/A/0','empty/A/1','empty/A/2'),1):records[key]['seconds']=i
    records['q1/A/1'].update(status='truncated_or_invalid',finish_reason='length',usage=None)
    result=summarize(manifest,records,'fixed',bootstrap=20,permutations=20);a=result['arms']['A']['resources']
    assert a['recorded_attempts']==6 and a['valid_completed_attempts']==5 and a['nonabstained_completed_count']==2
    assert a['observed_tokens']=={'prompt_tokens':50,'completion_tokens':25,'total_tokens':75}
    assert a['missing_usage_counts']=={'prompt_tokens':1,'completion_tokens':1,'total_tokens':1}
    assert a['latency']['recorded_attempts']['mean_seconds']==3.5
    assert a['latency']['recorded_attempts']['p50_seconds']==3.5
    assert a['latency']['valid_completed']['p50_seconds']==4
    assert a['tokens_per_answered_attempt']==37.5 and a['answered_attempt_mean_reported_tokens']==15
    assert a['usd'] is None
