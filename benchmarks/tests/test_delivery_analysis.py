import pytest


def data():
    queries=[{'id':'one','split':'test','family':'delayed_correction','kind':'assertion','cluster_id':'entity-1','scenario_family':'test:correction:one'},
             {'id':'dev','split':'dev','family':'delayed_correction','kind':'assertion','cluster_id':'entity-2','scenario_family':'dev:correction:one'},
             {'id':'event','split':'test','family':'correction_before_replacement','kind':'event','cluster_id':'entity-3','scenario_family':'test:event:one'}]
    labels=['Global temporal','Scalar clock','Filter after projection','Ordinary SQL receipt filter','Delivery projection','Delivery explicit item view']
    methods={label:{'per_query':{q['id']:{'gold_support':['event:e'] if q['kind']=='event' else ['assertion:a'],
        'missing_support':[] if label in ('Delivery projection','Delivery explicit item view') else ['missing'],
        'results':[],'leaks':[]} for q in queries},'stability':{'matching_repeated_signatures':3,'comparisons':3}} for label in labels}
    return {'status':'complete','query_manifest':queries,'methods':methods,'comparison':{},'fixture_sha256':'abc','provenance':{'git_commit':'frozen'}}


def test_analysis_uses_only_test_claim_cases_and_declares_family():
    from benchmarks.delivery_analysis import analyze
    result=analyze(data(),samples=100)
    assert result['primary_query_ids']==['one']
    assert result['source_run_commit']=='frozen'
    assert len(result['primary_comparisons'])==6 # pooled and present-family, three contrasts
    assert all(row['queries']==1 and row['family_size']==6 for row in result['primary_comparisons'].values())
    assert result['item_extension_comparisons']['event_notice_support']['queries']==1
    assert 'not numerically equivalent' in result['compatibility_note']


def test_analysis_refuses_unstable_or_incomplete_result():
    from benchmarks.delivery_analysis import analyze
    value=data();value['status']='running'
    with pytest.raises(ValueError,match='complete'):analyze(value,samples=100)
    value=data();value['methods']['Delivery projection']['stability']['matching_repeated_signatures']=2
    with pytest.raises(ValueError,match='unstable'):analyze(value,samples=100)
