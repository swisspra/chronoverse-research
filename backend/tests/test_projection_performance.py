"""Bounded ledger reads must preserve historical lifecycle projection."""
from chronoverse.models import AssertionInput, EventInput, QueryRequest
from chronoverse.store import Store


def test_bulk_projection_bounds_event_reads_and_preserves_knowledge_cutoffs(tmp_path):
    store=Store(tmp_path/'ledger.db',seed=False)
    for i in range(30):
        store.add_assertion(AssertionInput(id=f'a-{i:02}',subject='Harbor',predicate='report',object=f'item {i}',valid_from='2026-01-01',recorded_at='2026-01-01',evidence=[{'title':'Source','text':'Harbor report'}]))
        if i<10:
            store.add_event(f'a-{i:02}',EventInput(id=f'e-{i:02}',type='retract',effective_at='2026-04-01',recorded_at='2026-05-01' if i<5 else '2026-10-01',reason='Source withdrawn',source='Synthetic notice'))
    statements=[]
    store._db.set_trace_callback(statements.append)
    result=store.query(QueryRequest(query='Harbor',valid_at='2026-09-01',known_at='2026-09-01',limit=100))
    assert [r['id'] for r in result['results']]==[f'a-{i:02}' for i in range(5,30)]
    assert all(r['events']==[] for r in result['results'])
    reads=[s for s in statements if s.lstrip().upper().startswith('SELECT') and 'EVENTS' in s.upper()]
    assert len(reads)<=2, f'Event reads grew with assertion count: {len(reads)}'
    history=store.query(QueryRequest(query='Harbor',valid_at='2026-04-01',known_at='2026-09-01',include_retired=True,limit=100))
    assert len(history['results'])==30
    assert [r['id'] for r in history['results'] if r['status']=='retracted']==[f'a-{i:02}' for i in range(5)]
    early=store.query(QueryRequest(query='Harbor',valid_at='2026-09-01',known_at='2026-04-30',limit=100))
    assert len(early['results'])==30 and all(r['events']==[] for r in early['results'])
    store.close()
