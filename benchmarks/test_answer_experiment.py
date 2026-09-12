"""Offline localhost transport, budget, provenance-input and retry regressions."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest

from benchmarks.answer_experiment import PROMPT, digest, execute, prepare, render_prompt, score_answer


def rows():
    return [{'query_id':'q1','arm':arm,'question':'How many?','recipient_id':'R','valid_at':'2026-01-01',
             'known_at':'2026-01-02','received_by':'2026-01-02','context':[{'id':'assertion:x','text':'2 injured'}],
             'prompt_sha256':digest(PROMPT.read_bytes()),'expected_answers':['2'],
             'gold_support_ids':['assertion:x'],'visible_ids':['assertion:x'],'stale_ids':[],
             'answerable':True,'family':'test','event_only':False} for arm in 'ABCDE']


def prepared(data=None):
    data=rows() if data is None else data
    requests,estimate=prepare(data,PROMPT.read_text(),'test-model',max_input_tokens=5000,long_max_input_tokens=6000,max_completion_tokens=100)
    return data,requests,estimate


@pytest.fixture
def server():
    state={'calls':0,'mode':'ok','bodies':[]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            state['calls']+=1
            state['bodies'].append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            if state['mode']=='error':
                self.send_response(500);self.end_headers();self.wfile.write(b'private credential echo');return
            response={'id':'fake','model':None if state['mode']=='unknown-model' else ('fallback-model' if state['mode']=='fallback' and state['calls']>1 else 'test-model'),'choices':[{'message':{'content':'There were 2 injured.\nCITATIONS: ["assertion:x"]'},
                'finish_reason':'length' if state['mode']=='truncated' else 'stop'}],
                'usage':{'prompt_tokens':100,'completion_tokens':101 if state['mode']=='over-budget' else 20}}
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(response).encode())
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=http.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{http.server_port}/v1',state
    http.shutdown();thread.join();http.server_close()


def dispatch(tmp_path,server,**kwargs):
    data,requests,estimate=prepared()
    return execute(requests,data,estimate,base_url=server[0],key='never-print-this',checkpoint=tmp_path/'checkpoint.json',
        max_total_input_tokens=kwargs.get('input',100000),max_total_output_tokens=kwargs.get('output',1500))


def test_local_transport_three_repeats_dedup_and_gold_exclusion(tmp_path,server):
    result=dispatch(tmp_path,server)
    assert server[1]['calls']==15
    assert all(r['status']=='complete' and r['scoring']['answer_closed_form_match'] for r in result['requests'].values())
    dispatch(tmp_path,server);assert server[1]['calls']==15
    assert all(b['temperature']==0 and b['reasoning_effort']=='low' and b['max_completion_tokens']==100 for b in server[1]['bodies'])
    assert 'never-print-this' not in (tmp_path/'checkpoint.json').read_text()
    row=rows()[0];before=render_prompt(row,PROMPT.read_text())
    row.update(expected_answers=['SECRET-GOLD'],gold_support_ids=['SECRET-ID'],visible_ids=['SECRET-VISIBLE'])
    assert render_prompt(row,PROMPT.read_text())==before


def test_budget_and_hash_reject_before_network(tmp_path,server):
    with pytest.raises(ValueError,match='reservation'):dispatch(tmp_path,server,output=1499)
    assert server[1]['calls']==0
    data=rows();data[2]['prompt_sha256']='bad'
    with pytest.raises(ValueError,match='hash'):prepared(data)
    data=rows();data[0]['context'][0]['text']='x'*10000
    with pytest.raises(ValueError,match='no silent truncation'):prepared(data)


def test_uncertain_error_is_never_retried_or_leaked(tmp_path,server):
    server[1]['mode']='error'
    with pytest.raises(RuntimeError,match='uncertain'):dispatch(tmp_path,server)
    assert server[1]['calls']==1
    assert 'private credential echo' not in (tmp_path/'checkpoint.json').read_text()
    with pytest.raises(ValueError,match='Automatic retry refused'):dispatch(tmp_path,server)
    assert server[1]['calls']==1


def test_truncation_is_not_scored_or_retried(tmp_path,server):
    server[1]['mode']='truncated';result=dispatch(tmp_path,server)
    assert all(r['status']=='truncated_or_invalid' and 'scoring' not in r for r in result['requests'].values())
    dispatch(tmp_path,server);assert server[1]['calls']==15


def test_provider_budget_breach_stops_and_blocks_resume(tmp_path,server):
    server[1]['mode']='over-budget'
    with pytest.raises(RuntimeError,match='reservation'):dispatch(tmp_path,server)
    assert server[1]['calls']==1
    with pytest.raises(ValueError,match='Automatic retry refused'):dispatch(tmp_path,server)


@pytest.mark.parametrize('mode,guard',[('over-budget','budget_breach'),('unknown-model','model_guard_failure')])
def test_interrupt_after_terminal_checkpoint_cannot_skip_response_guards(tmp_path,server,monkeypatch,mode,guard):
    import benchmarks.answer_experiment as harness
    server[1]['mode']=mode
    persist=harness.atomic_checkpoint

    def interrupt_after_persist(path,state):
        persist(path,state)
        if any(record['status']!='pending' for record in state['requests'].values()):
            raise KeyboardInterrupt('Simulated interruption after durable response write')

    monkeypatch.setattr(harness,'atomic_checkpoint',interrupt_after_persist)
    with pytest.raises(KeyboardInterrupt):dispatch(tmp_path,server)
    saved=json.loads((tmp_path/'checkpoint.json').read_text())
    assert next(iter(saved['requests'].values())).get(guard)
    monkeypatch.setattr(harness,'atomic_checkpoint',persist)
    with pytest.raises(ValueError,match='Automatic retry refused'):dispatch(tmp_path,server)
    assert server[1]['calls']==1


@pytest.mark.parametrize('mode,expected_calls',[('fallback',2),('unknown-model',1)])
def test_actual_response_model_guard_keeps_raw_result_and_stops(tmp_path,server,mode,expected_calls):
    server[1]['mode']=mode
    with pytest.raises(RuntimeError,match='response model'):dispatch(tmp_path,server)
    assert server[1]['calls']==expected_calls
    state=json.loads((tmp_path/'checkpoint.json').read_text())
    failed=[r for r in state['requests'].values() if r.get('model_guard_failure')]
    assert len(failed)==1 and failed[0]['raw_answer'] and 'scoring' not in failed[0]
    with pytest.raises(ValueError,match='Automatic retry refused'):dispatch(tmp_path,server)


def test_required_values_typed_citations_and_semantic_limits():
    row=rows()[0];row['expected_answers']=['2','amber'];row['gold_support_ids'].append('event:e')
    row['visible_ids'].append('event:e');row['stale_ids']=['assertion:old']
    assert not score_answer('There were 12 injured and amber.\n["assertion:x"]',row)['answer_closed_form_match']
    result=score_answer('2 injured and amber.\n["assertion:x", "event:e", "assertion:old"]',row)
    assert result['answer_closed_form_match'] and result['support_recall']==1
    assert result['citation_leak_ids']==['assertion:old'] and result['stale_citation_ids']==['assertion:old']
    assert 'not adjudicated' in result['content_leakage']


def test_equivalent_support_is_eligible_and_all_groups_are_required():
    row=rows()[0];row['gold_support_ids']=['assertion:x','event:notice']
    row['support_equivalence_groups']=[{'required_id':'assertion:x','acceptable_ids':['assertion:x','evidence:p']},
        {'required_id':'event:notice','acceptable_ids':['event:notice']}]
    row['visible_ids']=['assertion:x','evidence:p','event:notice']
    row['context']=[{'id':id,'text':'source'} for id in row['visible_ids']]
    score=score_answer('2\nCITATIONS: ["evidence:p", "event:notice"]',row)
    assert score['equivalent_support_complete'] and score['equivalent_support_recall']==1
    assert not score['support_complete'] and score['support_recall']==.5
    assert score_answer('2\n["evidence:p"]',row)['equivalent_support_recall']==.5
    row['stale_ids']=['evidence:p']
    score=score_answer('2\n["evidence:p", "event:notice"]',row)
    assert not score['equivalent_support_complete'] and score['stale_citation_ids']==['evidence:p']
    row['stale_ids']=[];row['visible_ids'].remove('evidence:p')
    score=score_answer('2\n["evidence:p", "event:notice"]',row)
    assert not score['equivalent_support_complete'] and score['citation_leak_ids']==['evidence:p']
    row['visible_ids'].append('evidence:p');row['context']=[{'id':'event:notice','text':'source'}]
    assert not score_answer('2\n["evidence:p", "event:notice"]',row)['equivalent_support_complete']


@pytest.mark.parametrize('groups',[[],[{'required_id':'wrong','acceptable_ids':[]}],
    [{'required_id':'assertion:x','acceptable_ids':['assertion:x']},{'required_id':'assertion:x','acceptable_ids':[]}],
    [{'required_id':'assertion:x','acceptable_ids':'assertion:x'}]])
def test_malformed_equivalence_groups_fail_before_dispatch_and_scoring(groups):
    data=rows();data[0]['support_equivalence_groups']=groups
    with pytest.raises(ValueError,match='[Ss]upport'):
        prepared(data)
    with pytest.raises(ValueError,match='[Ss]upport'):
        score_answer('2\n["assertion:x"]',data[0])


@pytest.mark.parametrize('changed',['manifest','prompt'])
def test_main_rejects_input_drift_after_dispatch_without_misattribution(tmp_path,monkeypatch,changed):
    import sys
    import benchmarks.answer_experiment as harness
    manifest=tmp_path/'contexts.jsonl';manifest.write_text('\n'.join(json.dumps(row) for row in rows()))
    prompt=tmp_path/'prompt.txt';prompt.write_bytes(PROMPT.read_bytes())
    key=tmp_path/'key';key.write_text('offline')
    class Guard:
        def __init__(self,**kwargs):pass
        def write_json(self,*args):pytest.fail('Changed inputs must not publish a result.')
    def fake_execute(*args,**kwargs):
        (manifest if changed=='manifest' else prompt).write_text('mutated after dispatch')
        return {'requests':{},'actual_response_model':'fixed'}
    monkeypatch.setattr(harness,'BenchmarkRun',Guard);monkeypatch.setattr(harness,'execute',fake_execute)
    monkeypatch.setattr(sys,'argv',['answer_experiment','--mode','run','--manifest',str(manifest),'--prompt',str(prompt),'--model','fixed',
        '--base-url','http://localhost/v1','--key-file',str(key),'--max-input-tokens','10000','--max-completion-tokens','100',
        '--max-total-input-tokens','100000','--max-total-output-tokens','1500'])
    with pytest.raises(RuntimeError,match='changed during the run'):harness.main()
