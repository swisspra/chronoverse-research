"""No paid calls: fixed-pool integrity, native protocol and money regressions."""
from copy import deepcopy
import json
import math
from pathlib import Path
import pytest
from benchmarks.openrouter_rerank import ACTUAL_MODEL,MODEL,ROOT,execute,metrics,requests_for,sources,validate_response


def requests():return [{'query_id':str(i),'candidates':['a','b'],'body':{'model':MODEL,'query':'q'+str(i),'documents':['source a','source b'],'top_n':2}} for i in range(2)]


def response():return {'model':ACTUAL_MODEL,'results':[{'index':1,'relevance_score':.8},{'index':0,'relevance_score':.2}],'usage':{'cost':.001,'search_units':1}}


def run(tmp_path,transport,**kw):return execute(requests(),base_url='http://localhost/v1',key='secret-never-persist',checkpoint=tmp_path/'state.json',max_usd=kw.pop('max_usd','.02'),input_hashes={'fixed':'input'},transport=transport,**kw)


def test_exact_native_cache_and_budget_reservation_before_dispatch(tmp_path):
    calls=[]
    def send(endpoint,key,body,timeout):
        assert endpoint.endswith('/rerank') and body['documents']==['source a','source b']
        calls.append(body);return response()
    with pytest.raises(ValueError,match='reservation'):run(tmp_path,send,max_usd='.019')
    assert not calls
    state=run(tmp_path,send);assert len(calls)==2
    assert all(row['ranked_ids']==['b','a'] for row in state['requests'].values())
    run(tmp_path,send);assert len(calls)==2
    assert 'secret-never-persist' not in (tmp_path/'state.json').read_text()
    with pytest.raises(ValueError,match='identity'):run(tmp_path,send,max_usd='.03')


@pytest.mark.parametrize('failure',['timeout','unknown-cost','overspend','chat'])
def test_uncertain_or_invalid_response_is_retained_and_never_retried(tmp_path,failure):
    calls=[]
    def send(*args):
        calls.append(1)
        if failure=='timeout':raise TimeoutError('credential-bearing error must not be logged')
        value=response()
        if failure=='unknown-cost':value['usage']={}
        if failure=='overspend':value['usage']['cost']=.011
        if failure=='chat':value={'model':'chat-model','choices':[{'message':{'content':'answer'}}]}
        return value
    with pytest.raises(RuntimeError):run(tmp_path,send)
    assert len(calls)==1
    state=json.loads((tmp_path/'state.json').read_text());row=next(iter(state['requests'].values()))
    assert row['status']!='complete'
    if failure!='timeout':assert 'response' in row
    with pytest.raises(ValueError,match='retry'):run(tmp_path,send)
    assert len(calls)==1 and 'credential-bearing' not in (tmp_path/'state.json').read_text()


@pytest.mark.parametrize('change',[lambda r:r['results'][0].update(index=0),lambda r:r['results'][0].update(index=2),
    lambda r:r['results'][0].update(relevance_score=float('nan')),lambda r:r.update(model='other'),lambda r:r['results'].pop()])
def test_native_response_validation(change):
    value=response();change(value)
    with pytest.raises(ValueError):validate_response(value,2)


def test_independent_ndcg_uses_full_gold_not_candidate_pool():
    value=metrics(['wrong','positive'],{'positive':1,'outside-pool':1})
    assert value['ndcg@10']==pytest.approx((1/math.log2(3))/(1+1/math.log2(3)))
    assert value['recall@10']==.5 and value['mrr@10']==.5 and value['hit@1']==0


def test_real_official_frozen_pools_and_gold_free_request_bodies():
    data=ROOT/'.benchmark-data/scifact';source,documents,qrels=sources(ROOT/'docs/benchmarks-v2/rerank-results.json',data/'canonical-records.jsonl',data/'queries.jsonl',data/'qrels/test.tsv')
    made=requests_for(source,documents);assert len(made)==300 and len(qrels)==300
    assert all(len(r['candidates'])==50 and r['body']['documents']==[documents[id] for id in r['candidates']] for r in made)
    poisoned=deepcopy(source)
    for row in poisoned['per_query']:row['gold']=['POISON'];row['expected_answer']='POISON'
    assert requests_for(poisoned,documents)==made
