import re


class Tokenizer:
    def num_special_tokens_to_add(self,pair=False):return 2
    def __call__(self,text,**kwargs):
        offsets=[m.span() for m in re.finditer(r'\S+',text)]
        value={'input_ids':list(range(len(offsets)+(2 if kwargs.get('add_special_tokens',True) else 0)))}
        if kwargs.get('return_offsets_mapping'):value['offset_mapping']=offsets
        return value


def row(qid='q'):
    return {'question_id':qid,'question':'Where is my bag?','question_date':'2024/01/02 (Tue) 12:00',
        'question_type':'single-session-user','answer':'GOLD_SECRET','answer_session_ids':['old'],
        'haystack_session_ids':['old','future'],'haystack_dates':['2024/01/01 (Mon) 12:00','2024/01/03 (Wed) 12:00'],
        'haystack_sessions':[[{'role':'user','content':'My bag is red.','has_answer':True}],
                             [{'role':'user','content':'My bag is blue.','has_answer':False}]]}


def test_chunks_preserve_all_exact_text_and_token_bound():
    from benchmarks.longmemeval_rag import split_text
    text='user:  '+('one two three four five\n'*10)
    chunks=split_text(text,Tokenizer(),max_tokens=5)
    assert ''.join(c['text'] for c in chunks)==text
    assert all(c['model_tokens']<=5 for c in chunks)
    assert len(chunks)>1


def test_gold_free_ingress_and_independent_question_scopes():
    from benchmarks.longmemeval_rag import build_ledger, public_ingress
    import json
    one=public_ingress(row('q1'));two=public_ingress(row('q2'))
    assert 'GOLD_SECRET' not in json.dumps(one) and 'has_answer' not in json.dumps(one) and 'answer_session_ids' not in one
    a=build_ledger(one,Tokenizer());b=build_ledger(two,Tokenizer())
    assert {c['id'] for c in a}.isdisjoint(c['id'] for c in b)
    assert [c['text'] for c in a]==[c['text'] for c in b]


def test_date_gate_changes_only_candidate_pool_not_scores():
    from benchmarks.longmemeval_rag import build_ledger, public_ingress, select
    scope=public_ingress(row());chunks=build_ledger(scope,Tokenizer())
    scores=[.2,.9]
    assert select(scope,chunks,scores,cutoff=False,limit=5)[0]['session_id']=='future'
    filtered=select(scope,chunks,scores,cutoff=True,limit=5)
    assert [c['session_id'] for c in filtered]==['old'] and filtered[0]['score']==.2
    assert all(c['question_id']=='q' for c in filtered)


def test_qrels_only_score_session_support_and_abstention_separately():
    from benchmarks.longmemeval_rag import score_support
    q=row();result=score_support(q,[{'session_id':'old'},{'session_id':'old'}])
    assert result['support_session_recall']==1 and result['support_sessions_returned']==1
    absent=row('q_abs');absent['answer_session_ids']=[]
    value=score_support(absent,[{'session_id':'future'}])
    assert value['support_session_recall'] is None and value['abstention_question'] and not value['empty_context']
    missing=row();missing['answer_session_ids']=['not-in-ledger']
    assert score_support(missing,[])['qrel_coverage_complete'] is False


def test_cross_question_candidate_is_rejected_even_with_shared_text():
    import pytest
    from benchmarks.longmemeval_rag import public_ingress,build_ledger,select
    one=public_ingress(row('one'));foreign=build_ledger(public_ingress(row('other')),Tokenizer())
    with pytest.raises(ValueError,match='Cross-question'):
        select(one,foreign,[1.0]*len(foreign),cutoff=False,limit=5)


def test_abstention_retained_session_ids_are_not_positive_recall():
    from benchmarks.longmemeval_rag import score_support
    result=score_support(row('question_abs'),[{'session_id':'old'}])
    assert result['official_answer_session_ids']==['old']
    assert result['support_session_recall'] is None


def test_snapshot_fingerprint_includes_nested_pooling_config(tmp_path):
    from benchmarks.longmemeval_rag import snapshot_hashes
    (tmp_path/'1_Pooling').mkdir();config=tmp_path/'1_Pooling/config.json'
    config.write_text('{"pooling":"mean"}')
    first=snapshot_hashes(tmp_path)
    assert '1_Pooling/config.json' in first
    config.write_text('{"pooling":"max"}')
    assert snapshot_hashes(tmp_path)!=first
