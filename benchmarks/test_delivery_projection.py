from copy import deepcopy
from benchmarks.delivery_projection import DeliveryStore, SQLReceiptStore
from chronoverse.models import QueryRequest


def fixture():
    return {
        'assertions': [
            dict(id='old', subject='Harbor', predicate='reported count', object='18', summary='', world='main', plane='report', perspective='wire', valid_from='2024-01-01', recorded_at='2024-01-01', evidence=[dict(title='Report',text='Initial report:18',synthetic=True,recorded_at='2024-01-01')]),
            dict(id='new', subject='Harbor', predicate='reported count', object='8', summary='', world='main', plane='report', perspective='wire', valid_from='2024-01-01', recorded_at='2024-01-02', evidence=[dict(title='Correction',text='Corrected report:8',synthetic=True,recorded_at='2024-01-02')]),
        ],
        'events':[dict(id='correction',assertion_id='old',type='correct',effective_at='2024-01-01',recorded_at='2024-01-02',replacement_id='new',reason='Synthetic correction',source='Synthetic wire')],
        'receipts':[
            dict(id='r1',recipient_id='A',item_type='assertion',item_id='old',received_at='2024-01-01',recorded_at='2024-01-01'),
            dict(id='r2',recipient_id='A',item_type='evidence',item_id='old-e1',received_at='2024-01-01',recorded_at='2024-01-01'),
            dict(id='r3',recipient_id='A',item_type='event',item_id='correction',received_at='2024-01-03',recorded_at='2024-01-03'),
            dict(id='r4',recipient_id='A',item_type='assertion',item_id='new',received_at='2024-01-03T01:00:00Z',recorded_at='2024-01-03T01:00:00Z'),
            dict(id='r5',recipient_id='A',item_type='evidence',item_id='new-e1',received_at='2024-01-04',recorded_at='2024-01-04'),
        ],
    }


def query(store, at, known='2024-01-05', delivery='A'):
    return store.query_for(delivery,at,QueryRequest(query='',known_at=known,valid_at='2024-01-04',plane='report'))


def test_unreceived_correction_does_not_retire_deliverys_old_report(tmp_path):
    with DeliveryStore.from_fixture(tmp_path/'lab.db',fixture()) as store:
        result=query(store,'2024-01-02')
        assert [r['id'] for r in result['results']]==['old']
        assert result['results'][0]['events']==[]
        assert result['results'][0]['status']=='active'
        assert query(store,'2024-01-02',delivery='unopened')['results']==[]


def test_correction_received_before_replacement_yields_empty_context(tmp_path):
    with DeliveryStore.from_fixture(tmp_path/'lab.db',fixture()) as store:
        assert query(store,'2024-01-03')['results']==[]
        result=query(store,'2024-01-03T01:00:00Z')['results']
        assert [r['id'] for r in result]==['new']
        assert result[0]['evidence']==[]
        assert len(query(store,'2024-01-04')['results'][0]['evidence'])==1


def test_late_receipt_log_and_microsecond_boundary(tmp_path):
    data=fixture();data['receipts'][0]['received_at']='2024-01-01T00:00:00.123456Z';data['receipts'][0]['recorded_at']='2024-01-02'
    with DeliveryStore.from_fixture(tmp_path/'lab.db',data) as store:
        assert query(store,'2024-01-01T00:00:00.123455Z')['results']==[]
        assert query(store,'2024-01-01T00:00:00.123456Z',known='2024-01-01')['results']==[]
        assert [r['id'] for r in query(store,'2024-01-01T00:00:00.123456Z')['results']]==['old']


def test_sql_reference_and_invisible_changes_preserve_projection(tmp_path):
    data=fixture()
    changed=deepcopy(data);changed['assertions'][1]['evidence'][0]['text']='SECRET unseen passage changing meaning'
    with DeliveryStore.from_fixture(tmp_path/'one.db',data) as one, DeliveryStore.from_fixture(tmp_path/'two.db',changed) as two, SQLReceiptStore.from_fixture(tmp_path/'sql.db',data) as sql:
        for at in ['2024-01-02','2024-01-03','2024-01-04']:
            expected=query(one,at)
            assert expected['results']==query(sql,at)['results']
        assert query(one,'2024-01-02')['results']==query(two,'2024-01-02')['results']
        assert query(one,'2024-01-03T01:00:00Z')['results']==query(two,'2024-01-03T01:00:00Z')['results']
