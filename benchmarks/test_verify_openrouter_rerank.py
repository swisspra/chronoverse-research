"""Synthetic native responses on real frozen pools; never reads live hosted output."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import pytest

from benchmarks.openrouter_rerank import evaluate,requests_for,sources
from benchmarks.verify_openrouter_rerank import ROOT,object_hash,sha,verify


@pytest.fixture(scope='module')
def synthetic_result():
    data=ROOT/'.benchmark-data/scifact';original_path=ROOT/'docs/benchmarks-v2/rerank-results.json'
    original,documents,qrels=sources(original_path,data/'canonical-records.jsonl',data/'queries.jsonl',data/'qrels/test.tsv')
    requests=requests_for(original,documents);old={r['id']:r for r in original['per_query']};state={'requests':{}}
    for request in requests:
        candidates=request['candidates'];ranked=old[request['query_id']]['reranked'];scores={id:(50-ranked.index(id))/50 for id in candidates}
        response={'model':'rerank-v3.5','results':[{'index':i,'relevance_score':scores[id]} for i,id in enumerate(candidates)],'usage':{'cost':.001,'search_units':1}}
        key=object_hash({'endpoint':'https://openrouter.ai/api/v1/rerank',**request})
        state['requests'][key]={'query_id':request['query_id'],'candidates':candidates,'status':'complete','response':response,
            'ranked_ids':ranked,'scores':scores,'cost_usd':'0.001','reserved_usd':'0.01','seconds':.25,'input_sha256':object_hash(request['body'])}
    commit=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD']).decode().strip()
    paths=['docs/benchmarks-v2/rerank-results.json','.benchmark-data/scifact/canonical-records.jsonl','.benchmark-data/scifact/queries.jsonl',
        '.benchmark-data/scifact/qrels/test.tsv','benchmarks/openrouter_rerank.py','docs/benchmarks-next/OPENROUTER-RERANK-PROTOCOL.md']
    return {'status':'complete','provenance':{'git_commit':commit},'input_files_sha256':{p:sha((ROOT/p).read_bytes()) for p in paths},
        'parameters':{'requested_model':'cohere/rerank-v3.5','actual_model':'rerank-v3.5'},
        'estimate':{'input_sha256':object_hash(requests),'requests':300,'documents_per_request':50,'total_reservation_usd':'3.00'},
        'requests':state['requests'],**evaluate(original,qrels,state)}


def test_readonly_full_verifier_checks_all_native_scores_and_metrics(tmp_path,synthetic_result):
    path=tmp_path/'synthetic-native.json';path.write_text(json.dumps(synthetic_result));before=path.read_bytes()
    result=verify(path)
    assert result['status']=='verified' and result['queries']==300 and result['candidate_score_checks']==15000
    assert result['cost_usd']=='0.300'
    assert path.read_bytes()==before and list(tmp_path.iterdir())==[path]


@pytest.mark.parametrize('corruption',['rank','index','cost','metric','source-hash','pool','paired'])
def test_corrupt_copy_fails_without_touching_original(tmp_path,synthetic_result,corruption):
    broken=deepcopy(synthetic_result);first=next(iter(broken['requests'].values()))
    if corruption=='rank':first['ranked_ids'][0],first['ranked_ids'][1]=first['ranked_ids'][1],first['ranked_ids'][0]
    elif corruption=='index':first['response']['results'][1]['index']=first['response']['results'][0]['index']
    elif corruption=='cost':first['cost_usd']='0.009'
    elif corruption=='metric':broken['methods']['cohere_rerank_v3_5']['ndcg@10']+=.1
    elif corruption=='source-hash':broken['input_files_sha256']['benchmarks/openrouter_rerank.py']='0'*64
    elif corruption=='pool':first['candidates'][0],first['candidates'][1]=first['candidates'][1],first['candidates'][0]
    elif corruption=='paired':broken['paired_ndcg_contrasts']['rrf_minilm_top50']['p_holm']=.123
    path=tmp_path/'corrupt-copy.json';path.write_text(json.dumps(broken));before=path.read_bytes()
    with pytest.raises(ValueError):verify(path)
    assert path.read_bytes()==before
