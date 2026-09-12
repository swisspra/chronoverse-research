"""Classical receipt-scoped experimental adapters; production never imports this.

All model/ranking behavior is inherited from Store. Only context eligibility is
changed. These adapters are a lab capability demonstration, not an authorization
boundary or a claim to know an actual human's mental state.
"""
from collections import defaultdict
import json

from chronoverse.models import timestamp
from chronoverse.store import Store


def scoped_sql(request, alias='a'):
    conditions = [f'{alias}.recorded_at<=?', f'{alias}.valid_from<=?',
                  f'({alias}.valid_to IS NULL OR {alias}.valid_to>?)']
    params = [timestamp(request.known_at), timestamp(request.valid_at), timestamp(request.valid_at)]
    for key in ('world', 'plane', 'perspective'):
        if getattr(request, key) != 'all':
            conditions.append(f'{alias}.{key}=?')
            params.append(getattr(request, key))
    return ' AND '.join(conditions), params


class DeliveryStore(Store):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.receipts = []
        self._delivery_context = None
        self.strategy = 'delivery'

    @classmethod
    def from_fixture(cls, path, fixture):
        store = cls(path, seed=False)
        try:
            for start in range(0, len(fixture['assertions']), 500):
                store.add_assertions_atomic(fixture['assertions'][start:start+500])
            for row in sorted(fixture['events'], key=lambda e: (timestamp(e['recorded_at']), e['id'])):
                event = dict(row)
                store.add_event(event.pop('assertion_id'), event)
            store._db.execute('CREATE TABLE IF NOT EXISTS delivery_receipts (id TEXT PRIMARY KEY,recipient_id TEXT,item_type TEXT,item_id TEXT,received_at TEXT,recorded_at TEXT)')
            known_items = {('assertion', r['id']) for r in fixture['assertions']}
            for row in store._db.execute('SELECT payload FROM assertions'):
                known_items.update(('evidence', e['id']) for e in json.loads(row[0])['evidence'])
            known_items.update(('event', r['id']) for r in fixture['events'])
            for receipt in fixture['receipts']:
                row = {**receipt, 'received_at': timestamp(receipt['received_at']),
                       'recorded_at': timestamp(receipt['recorded_at'])}
                if row['received_at'] > row['recorded_at']:
                    raise ValueError('Receipt log cannot precede receipt.')
                if (row['item_type'], row['item_id']) not in known_items:
                    raise ValueError('Receipt references an unknown item.')
                store._db.execute('INSERT INTO delivery_receipts VALUES (?,?,?,?,?,?)',
                                  tuple(row[k] for k in ('id','recipient_id','item_type','item_id','received_at','recorded_at')))
                store.receipts.append(row)
            store._db.execute('CREATE INDEX receipts_by_delivery ON delivery_receipts(recipient_id,item_type,item_id,recorded_at,received_at)')
            store._db.commit()
            return store
        except BaseException:
            store.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def query_for(self, recipient, received_by, request):
        with self._lock:
            previous = self._delivery_context
            self._delivery_context = (recipient, timestamp(received_by))
            try:
                if self.strategy == 'scalar':
                    request = request.model_copy(update={'known_at': min(timestamp(request.known_at), timestamp(received_by))})
                result = super().query(request)
                result['delivery_view'] = {'recipient_id': recipient, 'received_by': timestamp(received_by),
                                           'strategy': self.strategy, 'meaning': 'Received evidence availability, not endorsement or truth.'}
                return result
            finally:
                self._delivery_context = previous

    def _visible_keys(self, known_at):
        recipient, received_by = self._delivery_context
        return {(r['item_type'], r['item_id']) for r in self.receipts
                if r['recipient_id'] == recipient and r['received_at'] <= received_by
                and r['recorded_at'] <= known_at}

    def _eligible(self, request):
        if self._delivery_context is None or self.strategy in ('global', 'scalar'):
            return super()._eligible(request)
        known, valid = timestamp(request.known_at), timestamp(request.valid_at)
        visible = self._visible_keys(known)
        if self.strategy == 'post_projection':
            rows = super()._eligible(request)
            return [{**row,
                     'evidence': [e for e in row['evidence'] if ('evidence', e['id']) in visible],
                     'events': [e for e in row['events'] if ('event', e['id']) in visible]}
                    for row in rows if ('assertion', row['id']) in visible]
        where, params = scoped_sql(request)
        raws = [json.loads(r[0]) for r in self._db.execute('SELECT a.payload FROM assertions a WHERE '+where+' ORDER BY a.id',params)]
        events = defaultdict(list)
        for r in self._db.execute('SELECT payload FROM events WHERE recorded_at<=? ORDER BY recorded_at,id',(known,)):
            event = json.loads(r[0])
            if ('event', event['id']) in visible:
                events[event['assertion_id']].append(event)
        result = []
        for raw in raws:
            if ('assertion', raw['id']) not in visible:
                continue
            raw['evidence'] = [e for e in raw['evidence'] if ('evidence', e['id']) in visible]
            row = self._project(raw, known, valid, events[raw['id']])
            if request.include_retired or (row['status'] == 'active' and (row['effective_valid_to'] is None or valid < row['effective_valid_to'])):
                result.append(row)
        return result


class SQLReceiptStore(DeliveryStore):
    """Ordinary SQL receipt joins and separate lifecycle state reconstruction.

    Uses neither the adapter's _visible_keys nor Store._project. Ranking is shared
    to isolate eligibility from embeddings and ranking weights.
    """
    def visible_keys(self, recipient, received_by, known_at):
        return {(r[0],r[1]) for r in self._db.execute(
            'SELECT DISTINCT item_type,item_id FROM delivery_receipts WHERE recipient_id=? AND received_at<=? AND recorded_at<=?',
            (recipient,timestamp(received_by),timestamp(known_at)))}

    def _eligible(self, request):
        if self._delivery_context is None:
            return super()._eligible(request)
        recipient, received_by = self._delivery_context
        known, valid = timestamp(request.known_at), timestamp(request.valid_at)
        where, params = scoped_sql(request)
        gate = 'EXISTS(SELECT 1 FROM delivery_receipts r WHERE r.recipient_id=? AND r.item_type=? AND r.item_id={item} AND r.received_at<=? AND r.recorded_at<=?)'
        raws = self._db.execute('SELECT a.payload FROM assertions a WHERE '+where+' AND '+gate.format(item='a.id')+' ORDER BY a.id',
                               [*params,recipient,'assertion',received_by,known]).fetchall()
        result = []
        for raw in raws:
            row = json.loads(raw[0])
            evidence_sql = "SELECT p.value FROM assertions a,json_each(a.payload,'$.evidence') p WHERE a.id=? AND json_extract(p.value,'$.recorded_at')<=? AND "+gate.format(item="json_extract(p.value,'$.id')")+' ORDER BY p.key'
            row['evidence'] = [json.loads(r[0]) for r in self._db.execute(evidence_sql,(row['id'],known,recipient,'evidence',received_by,known))]
            event_sql = 'SELECT e.payload FROM events e WHERE e.assertion_id=? AND e.recorded_at<=? AND '+gate.format(item='e.id')+' ORDER BY e.recorded_at,e.id'
            events = [json.loads(r[0]) for r in self._db.execute(event_sql,(row['id'],known,recipient,'event',received_by,known))]
            row['events'] = events
            status, boundary = 'active', row['valid_to']
            transitions = sorted(events,key=lambda e:(e['effective_at'],{'supersede':0,'correct':1,'retract':2}[e['type']],e['recorded_at'],e['id']))
            for event in transitions:
                if event['type']=='supersede':
                    boundary = min(boundary,event['effective_at']) if boundary else event['effective_at']
                if event['effective_at'] <= valid:
                    status = {'supersede':'superseded','correct':'corrected','retract':'retracted'}[event['type']]
            if not request.include_retired and (status!='active' or (boundary is not None and valid>=boundary)):
                continue
            row.update(status=status,effective_valid_to=boundary,score=0.0,
                       score_breakdown={'lexical':0.0,'vector':0.0,'graph':0.0},
                       explanation=f'{status.capitalize()} in the requested valid-time and knowledge-time snapshot; evidence and events are filtered by knowledge time.')
            result.append(row)
        return result
