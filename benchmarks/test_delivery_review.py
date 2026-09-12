"""Second-agent delivery regression checks: source cutoffs and warmed cache/graph isolation."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest
from chronoverse.models import QueryRequest
from chronoverse import semantic
from benchmarks.delivery_projection import DeliveryStore, SQLReceiptStore
from benchmarks.test_delivery_projection import fixture


@pytest.mark.parametrize('adapter',[DeliveryStore,SQLReceiptStore])
def test_early_receipt_does_not_bypass_source_recorded_cutoff(tmp_path,adapter):
    data=fixture()
    # Received/logged before source records entered the ledger: receipt time is
    # insufficient on its own, even when delivery time is later.
    for row in data['receipts']:
        row.update(received_at='2024-01-01',recorded_at='2024-01-01')
    data['assertions'][0]['evidence'][0]['recorded_at']='2024-01-02'
    with adapter.from_fixture(tmp_path/'cutoffs.db',data) as store:
        def run(known):
            return store.query_for('A','2024-01-04',QueryRequest(query='',known_at=known,valid_at='2024-01-04',plane='report'))
        early=run('2024-01-01T23:59:59.999999Z')['results']
        assert [r['id'] for r in early]==['old']
        assert early[0]['status']=='active' and early[0]['events']==[] and early[0]['evidence']==[]
        later=run('2024-01-02')['results']
        assert [r['id'] for r in later]==['new']
        assert [e['id'] for e in later[0]['evidence']]==['new-e1']


def received_fixture():
    old=deepcopy(fixture()['assertions'][0])
    old['evidence'].append(dict(title='Separate passage',text='quartzmarker confidential passage',synthetic=True,recorded_at='2024-01-01'))
    secret=deepcopy(old)
    secret.update(id='hidden',subject='SecretRoom',object='HiddenNode',evidence=[dict(title='Hidden source',text='hidden bulletin',synthetic=True,recorded_at='2024-01-01')])
    receipts=[]
    for delivery,items in [('A',[('assertion','old'),('evidence','old-e1'),('assertion','hidden'),('evidence','hidden-e1')]),('B',[('assertion','old'),('evidence','old-e1')])]:
        for kind,item in items:
            receipts.append(dict(id=f'{delivery}-{item}',recipient_id=delivery,item_type=kind,item_id=item,received_at='2024-01-01',recorded_at='2024-01-01'))
    receipts.append(dict(id='late-passage',recipient_id='A',item_type='evidence',item_id='old-e2',received_at='2024-01-03',recorded_at='2024-01-03'))
    return dict(assertions=[old,secret],events=[],receipts=receipts)


@pytest.mark.parametrize('adapter',[DeliveryStore,SQLReceiptStore])
def test_warmed_vectors_lexical_graph_and_concurrent_deliverys_stay_isolated(tmp_path,adapter,monkeypatch):
    monkeypatch.setenv('CHRONOVERSE_EMBEDDINGS','semantic')
    monkeypatch.setattr(semantic,'model_identity',lambda:('delivery-test',3))
    monkeypatch.setattr(semantic,'_embed',lambda text:(1.,0.,0.))
    monkeypatch.setattr(semantic,'_encode_documents',lambda texts:[[1.,0.,0.] if 'quartzmarker' in text else [0.,1.,0.] for text in texts])
    with adapter.from_fixture(tmp_path/'isolation.db',received_fixture()) as store:
        def run(delivery,at='2024-01-04',query='quartzmarker',perspective='wire'):
            return store.query_for(delivery,at,QueryRequest(query=query,known_at='2024-01-05',valid_at='2024-01-04',plane='report',perspective=perspective))
        assert [r['id'] for r in run('A')['results']]==['old']
        assert run('B')['results']==[]
        assert run('A','2024-01-02')['results']==[]
        assert run('A',perspective='A')['results']==[], 'Recipient identity must not replace source perspective.'
        assert {n['label'] for n in run('A',query='')['graph']['nodes']}=={'Harbor','18','SecretRoom','HiddenNode'}
        assert {n['label'] for n in run('B',query='')['graph']['nodes']}=={'Harbor','18'}
        assert run('unopened',query='')['graph']=={'nodes':[],'edges':[]}
        def check(delivery):
            result=run(delivery)
            assert result['delivery_view']['recipient_id']==delivery
            assert [r['id'] for r in result['results']]==(['old'] if delivery=='A' else [])
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(check,['A','B']*20))
