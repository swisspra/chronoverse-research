"""Independent scenario/gold review; never change relevance labels to fit Store."""
from collections import defaultdict
import json
from pathlib import Path
import pytest
from benchmarks.temporal_v2 import generate_fixture, visible_record, canonical_text, instant, apply_gate, selective_metrics, calibrate

FIXTURE = json.loads((Path(__file__).parents[1]/'data/temporal-v2.json').read_text())
BY_ID = {row['id']:row for row in FIXTURE['assertions']}
EVENTS=defaultdict(list)
for event in FIXTURE['events']:EVENTS[event['assertion_id']].append(event)


def test_frozen_fixture_is_reproducible_and_splits_entities_and_scenario_families():
    assert generate_fixture()==FIXTURE
    dev=[q for q in FIXTURE['queries'] if q['split']=='dev'];test=[q for q in FIXTURE['queries'] if q['split']=='test']
    assert len(dev)==40 and len(test)==114
    assert {q['entity_key'] for q in dev}.isdisjoint({q['entity_key'] for q in test})
    assert {q['family'] for q in dev}.isdisjoint({q['family'] for q in test})
    assert len(BY_ID)==206 and len(FIXTURE['events'])==38
    assert all(q['rationale'] and 'PLACEHOLDER' not in q['rationale'] for q in FIXTURE['queries'])


def expected_test_objects(q):
    family=q['family'];known=instant(q['scope']['known_at']);valid=instant(q['scope']['valid_at'])
    if family=='test_chained_succession':return {'Bea Rowan' if known<instant('2024-06-08') else 'Cy Morgan'}
    if family=='test_historical_after_chain':return {'Mira Vale'}
    if family=='test_confusable_role':return {'Iris North'}
    if family=='test_confusable_quantity':return {'24000 people'}
    if family=='test_near_name_entity':return {'Nora Hale'}
    if family=='test_chained_corrections':return {'8' if known<instant('2024-06-05') else '3'}
    if family=='test_microsecond_interval':return {'granted'} if instant('2024-06-01T12:00:00.123456Z')<=valid<instant('2024-06-01T12:00:01.123456Z') else set()
    if family=='test_late_evidence':return {'inspection note'} if known>=instant('2024-06-03T10:30:00Z') else set()
    if family=='test_retraction_boundary':return {'detected'} if known<instant('2024-06-04T09:00:00Z') else set()
    if family=='test_predicate_conflict':return {'July 9','July 10'}
    if family in ('test_missing_relation','test_nonexistent_entity','test_unrecorded_future'):return set()
    raise AssertionError(f'Unreviewed held-out scenario: {family}')


@pytest.mark.parametrize('query',[q for q in FIXTURE['queries'] if q['split']=='test'],ids=lambda q:q['id'])
def test_manual_held_out_gold_matches_separate_semantic_expectation(query):
    assert {BY_ID[aid]['object'] for aid in query['gold_assertion_ids']}==expected_test_objects(query)
    assert len(query['gold_assertion_ids'])==len(set(query['gold_assertion_ids']))
    for aid in query['gold_assertion_ids']:
        assert query['entity_key'] in BY_ID[aid]['subject']
        assert visible_record(BY_ID[aid],query['scope'],EVENTS) is not None


def test_late_evidence_is_absent_before_its_own_exact_knowledge_boundary():
    cases=[q for q in FIXTURE['queries'] if q['family']=='test_late_evidence' and q['entity_key']=='Vesper']
    before=next(q for q in cases if not q['gold_assertion_ids']);after=next(q for q in cases if q['gold_assertion_ids'])
    row=BY_ID[after['gold_assertion_ids'][0]]
    assert row['recorded_at']=='2024-01-01'
    old=visible_record(row,before['scope'],EVENTS);new=visible_record(row,after['scope'],EVENTS)
    assert old is not None and new is not None  # The record existed; its passage did not.
    assert old['evidence']==[]
    assert 'ammonia' not in canonical_text(old)
    assert 'ammonia' in canonical_text(new)


@pytest.fixture(scope='module')
def store():
    from chronoverse.store import Store
    from chronoverse.models import AssertionInput,EventInput
    ledger=Store(':memory:',seed=False)
    for row in FIXTURE['assertions']:ledger.add_assertion(AssertionInput(**row))
    for event in FIXTURE['events']:ledger.add_event(event['assertion_id'],EventInput(**{k:v for k,v in event.items() if k!='assertion_id'}))
    yield ledger
    ledger.close()


@pytest.mark.parametrize('query',FIXTURE['queries'],ids=lambda q:q['id'])
def test_store_eligibility_and_visible_evidence_match_independent_policy(store,query):
    from chronoverse.models import QueryRequest
    expected={row['id']:projected for row in FIXTURE['assertions'] if (projected:=visible_record(row,query['scope'],EVENTS)) is not None}
    # API display is capped at100; six boundary slices have102 eligible records.
    actual=store.query(QueryRequest(query='',limit=100,**query['scope']))
    assert actual['eligible_count']==len(expected)
    assert {row['id'] for row in actual['results']}<=set(expected)
    assert len(actual['results'])==min(100,len(expected))
    if len(expected)<=100:
        assert {row['id'] for row in actual['results']}==set(expected)
    for row in actual['results']:
        assert [e['text'] for e in row['evidence']]==[e['text'] for e in expected[row['id']]['evidence']]


def test_gate_preserves_native_order_and_retains_close_conflicting_candidates():
    assert apply_gate(['a','b','c'],{'a':.72,'b':.75,'c':.30},.50,.05)==['a','b']
    assert apply_gate(['a'],{'a':.20},.50,.05)==[]


def test_selective_metrics_penalize_wrong_extras_and_false_abstention():
    queries=[{'id':'positive','gold_assertion_ids':['a','b']},{'id':'empty','gold_assertion_ids':[]}]
    summary=selective_metrics({'positive':['a','wrong'],'empty':['wrong']},queries)
    assert summary['micro_precision']==pytest.approx(1/3)
    assert summary['micro_recall']==.5
    assert summary['empty_gold_abstention_rate']==0
    assert summary['conflict_complete_rate']==0
    abstained=selective_metrics({'positive':[],'empty':[]},queries)
    assert abstained['false_abstention_rate']==1
    assert abstained['micro_f0.5']==0


def test_calibration_ignores_held_out_rankings_and_labels():
    dev=[{'id':'dev-positive','gold_assertion_ids':['a']},{'id':'dev-empty','gold_assertion_ids':[]}]
    rankings={'dev-positive':['a','x'],'dev-empty':['x'],'test':['leak']}
    scores={'dev-positive':{'a':.8,'x':.3},'dev-empty':{'x':.3},'test':{'leak':.99}}
    first=calibrate(dev,rankings,scores)
    rankings['test']=['different'];scores['test']={'different':0.0}
    assert calibrate(dev,rankings,scores)==first

@pytest.mark.parametrize('query',[q for q in FIXTURE['queries'] if q['split']=='dev'],ids=lambda q:q['id'])
def test_manual_dev_gold_is_reviewed_before_gate_calibration(query):
    expected={
        'dev_numeric_predicate':{'240 people'},'dev_location_paraphrase':{'Pine Harbor'},
        'dev_world_scope':{'Ari Lane'},'dev_perspective':{'safe'},
        'dev_withdrawn_report':set(),'dev_missing_attribute':set(),
        'dev_disagreement':{'June 11','June 12'},'dev_expired_permission':set(),
    }
    if query['family']=='dev_delayed_appointment':
        objects={'Mira Vale' if instant(query['scope']['known_at'])<instant('2024-06-05') else 'Bea Rowan'}
    else:
        objects=expected[query['family']]
    assert {BY_ID[aid]['object'] for aid in query['gold_assertion_ids']}==objects
