"""Exact overlap cache: reuse, cohort invalidation, isolation and bounded admission."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from chronoverse.store import Store, _tokens
from chronoverse.models import AssertionInput, QueryRequest


def cache(**kwargs):
    from chronoverse.lexical_index import LexicalIndex
    return LexicalIndex(**kwargs)


def test_exact_unique_token_scores_unicode_duplicates_and_order():
    index=cache()
    texts=['alpha alpha','alpha beta','gamma','ภาษาไทย alpha','alpha alpha']
    assert index.score({'alpha','beta'},texts,_tokens)==[.5,1.,0.,.5,.5]
    assert index.score({'ภาษาไทย','alpha'},texts,_tokens)==[.5,.5,0.,1.,.5]
    assert index.score(set(),texts,_tokens)==[0.,0.,0.,0.,0.]
    assert index.score({'alpha'},[],_tokens)==[]
    assert index.score({'alpha'},['beta','alpha'],_tokens)==[0.,1.]
    assert index.score({'alpha'},['alpha','beta','alpha'],_tokens)==[1.,0.,1.]


def test_cache_hit_does_not_retokenize_documents_and_exact_edit_rebuilds():
    index=cache()
    assert index.score({'alpha'},['alpha','beta'],_tokens)==[1.,0.]
    def forbidden(text):
        pytest.fail('Retokenized an unchanged cached document cohort')
    assert index.score({'beta'},['alpha','beta'],forbidden)==[0.,1.]
    assert index.score({'gamma'},['alpha','gamma'],_tokens)==[0.,1.]


def test_overbudget_fallback_is_exact_and_retained_state_stays_bounded():
    index=cache(memory_limit=4096)
    index.score({'alpha'},['alpha'],_tokens)
    texts=[' '.join(f'token{i}' for i in range(3000)), 'token3']
    assert index.score({'token3','absent'},texts,_tokens)==[.5,.5]
    assert index.retained_bytes<=index.memory_limit
    assert index.statistics()['cached_documents']==0
    assert index.score({'token7'},texts,_tokens)==[1.,0.]
    assert index.retained_bytes<=index.memory_limit
    assert index.score({'new'},['new'],_tokens)==[1.]
    assert index.statistics()['cached_documents']==1


def test_posting_array_growth_is_counted():
    index=cache(memory_limit=4096)
    assert index.score({'same'},['same']*3000,_tokens)==[1.]*3000
    assert index.statistics()['cached_documents']==0
    assert index.retained_bytes<=4096


def test_concurrent_cohorts_never_mix_positions():
    index=cache()
    cases=[(['alpha','beta'],[1.,0.]), (['beta','alpha','alpha'],[0.,1.,1.])]*20
    def run(case):
        texts,expected=case
        assert index.score({'alpha'},texts,_tokens)==expected
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run,cases))


def test_store_scope_history_new_assertion_and_profile_isolation(tmp_path, monkeypatch):
    monkeypatch.delenv('CHRONOVERSE_EMBEDDINGS',raising=False)
    one=Store(tmp_path/'one.db',seed=False)
    two=Store(tmp_path/'two.db',seed=False)
    def add(store,id,subject='Harbor',**kw):
        store.add_assertion(AssertionInput(id=id,subject=subject,predicate='report',object='one',valid_from='2026-01-01',recorded_at='2026-01-01',evidence=[{'title':'Early','text':'initial'},{'title':'Late','text':'late-secret','recorded_at':'2026-05-01'}],**kw))
    add(one,'same')
    add(one,'foreign',world='elsewhere')
    add(two,'same',subject='Different')
    def query(store,known='2026-06-01',world='main'):
        return store.query(QueryRequest(query='late-secret',known_at=known,world=world))
    assert query(one,'2026-04-01')['results']==[]
    assert [r['id'] for r in query(one)['results']]==['same']
    assert query(one,'2026-04-01')['results']==[]
    assert [r['id'] for r in query(one,world='elsewhere')['results']]==['foreign']
    add(one,'added')
    assert [r['id'] for r in query(one)['results']]==['added','same']
    assert [r['subject'] for r in query(two)['results']]==['Different']
    assert one._lexical_index is not two._lexical_index
    one.close();two.close()
