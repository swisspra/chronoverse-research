from copy import deepcopy
import json

from benchmarks.delivery_projection import DeliveryStore
from benchmarks.test_delivery_projection import fixture
from chronoverse.models import QueryRequest


def request(text='Report', **changes):
    return QueryRequest(query=text, valid_at='2024-01-04', known_at='2024-01-05', plane='report', **changes)


def test_bulk_fixture_over_500_preserves_legacy_projection(tmp_path):
    data=fixture()
    for i in range(505):
        row=deepcopy(data['assertions'][0]);row['id']=f'extra-{i}'
        data['assertions'].append(row)
    with DeliveryStore.from_fixture(tmp_path/'bulk.sqlite3',data) as store:
        assert store._db.execute('SELECT COUNT(*) FROM assertions').fetchone()[0]==507
        assert [r['id'] for r in store.query_for('A','2024-01-02',request(''))['results']]==['old']


def test_orphan_passage_never_exposes_undelivered_parent_fields(tmp_path):
    from benchmarks.delivery_items import ItemDeliveryStore
    data=fixture();data['receipts']=[r for r in data['receipts'] if r['item_type']=='evidence']
    data['assertions'][0].update(subject='SECRET SUBJECT',object='SECRET VALUE',summary='SECRET SUMMARY')
    data['events']=[]
    with ItemDeliveryStore.from_fixture(tmp_path/'items.sqlite3',data) as store:
        result=store.query_for('A','2024-01-02',request('Initial report'))
        assert result['results'][0]['item_type']=='evidence'
        assert result['results'][0]['item_id']=='old-e1'
        assert 'SECRET' not in json.dumps(result)
        assert store.query_for('B','2024-01-02',request('Initial report'))['results']==[]
        assert store.query_for('A','2023-12-31',request('Initial report'))['results']==[]


def test_notice_before_replacement_including_future_effective_and_expired_parent(tmp_path):
    from benchmarks.delivery_items import ItemDeliveryStore
    data=fixture();data['assertions'][0]['valid_to']='2024-01-02'
    data['events'][0]['effective_at']='2024-01-10'
    with ItemDeliveryStore.from_fixture(tmp_path/'items.sqlite3',data) as store:
        rows=store.query_for('A','2024-01-03',request('Which correction notice is available?'))['results']
        assert [r['item_id'] for r in rows]==['correction']
        assert rows[0]['events'][0]['effective_at'].startswith('2024-01-10')
        assert rows[0]['evidence']==[] and rows[0]['item_type']=='event'
        assert store.query_for('A','2024-01-02',request('correction notice'))['results']==[]
        assert store.query_for('A','2024-01-03',request('capacity report'))['results']==[]


def test_item_source_cutoff_scope_and_text_cache_rewind(tmp_path):
    from benchmarks.delivery_items import ItemDeliveryStore
    data=fixture();data['receipts']=[r for r in data['receipts'] if r['item_type']=='evidence']
    data['assertions'][0]['evidence'][0]['recorded_at']='2024-01-04'
    with ItemDeliveryStore.from_fixture(tmp_path/'items.sqlite3',data) as store:
        future=request('Initial report')
        past=future.model_copy(update={'known_at':'2024-01-03'})
        assert store.query_for('A','2024-01-02',past)['results']==[]
        assert store.query_for('A','2024-01-02',future)['results']
        assert store.query_for('A','2024-01-02',past)['results']==[]
        assert store.query_for('A','2024-01-02',future.model_copy(update={'world':'other'}))['results']==[]


def test_event_gold_is_answerable_and_missing_notice_is_not_correct_abstention():
    from benchmarks.delivery_v3 import annotate_compact, aggregate
    query={'gold_assertion_ids':[],'gold_evidence_ids':[],'gold_event_ids':['event1'],'kind':'event'}
    row=annotate_compact(query,{'results':[],'eligible_count':0,'scope':{},'delivery_view':{}},set(),{})
    metrics=aggregate({'q':row})
    assert row['gold_support']==['event:event1']
    assert metrics['answerable_queries']==1 and metrics['empty_queries']==0
    assert metrics['false_abstention_rate']==1 and metrics['empty_abstention_rate'] is None


def test_question_entity_matching_does_not_use_gold():
    from benchmarks.delivery_v3 import entity_versions
    rows=[{'id':'a','subject':'Harbor','predicate':'count','object':'8','summary':'','valid_from':'2024-01-01','valid_to':None,'recorded_at':'2024-01-01','evidence':[]}]
    assert entity_versions('Tell me Harbor count',rows)['contexts'][0]['id']=='a'
    assert entity_versions('Unrelated question',rows)['contexts']==[]


def test_small_actual_runner_gzip_and_stability(tmp_path):
    import gzip
    import os
    import subprocess
    import sys
    from pathlib import Path
    data=fixture()
    data['queries']=[{'id':'tiny','split':'dev','family':'delayed_correction','kind':'assertion',
        'recipient_id':'A','query':'Harbor report','scope':{'valid_at':'2024-01-04','known_at':'2024-01-05',
        'received_by':'2024-01-02','world':'main','plane':'report','perspective':'all'},
        'gold_assertion_ids':['old'],'gold_evidence_ids':['old-e1'],'gold_event_ids':[]}]
    source=tmp_path/'fixture.json.gz';source.write_bytes(gzip.compress(json.dumps(data).encode(),mtime=0))
    out=tmp_path/'out'
    command=[sys.executable,'-m','benchmarks.delivery_v3','--fixture',str(source),'--output-dir',str(out),
             '--embedding-mode','hashed','--allow-dirty']
    completed=subprocess.run(command,cwd=Path(__file__).resolve().parents[2],capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    result=json.loads((out/'results.json').read_text())
    assert result['comparison']['sql_delivery_identical_results']==1
    assert len(result['methods'])==6
    assert all(method['stability']=={'matching_repeated_signatures':1,'comparisons':1} for method in result['methods'].values())
    assert result['methods']['Delivery projection']['metrics']['complete_support_rate']==1
    contexts=json.loads((out/'retrieval-contexts.json').read_text())
    assert contexts['arms']['B_all_versions_question_entity']['tiny']['entity_from_question']=='Harbor'
    assert len(result['fixture_raw_sha256'])==64


def test_received_passage_before_parent_recording_uses_own_source_clock(tmp_path):
    from benchmarks.delivery_items import ItemDeliveryStore
    data=fixture();data['events']=[]
    data['assertions'][0]['recorded_at']='2024-02-01'
    data['receipts']=[r for r in data['receipts'] if r['id']=='r2']
    with ItemDeliveryStore.from_fixture(tmp_path/'late-parent.sqlite3',data) as store:
        rows=store.query_for('A','2024-01-02',request('Initial report'))['results']
        assert [row['item_id'] for row in rows]==['old-e1']
        assert all(row['item_type']=='evidence' for row in rows)


def test_changed_repeat_signature_fails_with_method_and_query_id():
    import pytest
    from benchmarks.delivery_v3 import require_stable
    with pytest.raises(RuntimeError,match='Delivery.*query-42'):
        require_stable('Delivery','query-42','first','changed')
    assert require_stable('Delivery','query-42','same','same')==1
