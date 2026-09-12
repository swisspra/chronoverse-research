"""Explicit lab item-view extension; never imported by the production application.

Uses unchanged Store ranking over assertion contexts plus received standalone
passages. Explicit notice wording additionally permits event items, even when
future-effective or the parent interval has ended. Item text never includes an
undelivered parent claim or replacement. This is a different retrieval capability,
not a fix silently applied to the five assertion-only comparison arms.
"""
import json
import re

from benchmarks.delivery_projection import DeliveryStore
from chronoverse.models import timestamp

NOTICE_WORDS = frozenset({'notice', 'notices', 'correction', 'retraction', 'supersession'})


class ItemDeliveryStore(DeliveryStore):
    def _eligible(self, request):
        rows = super()._eligible(request)
        if self._delivery_context is None:
            return rows
        recipient, received_by = self._delivery_context
        known, valid = timestamp(request.known_at), timestamp(request.valid_at)
        attached = {e['id'] for row in rows for e in row['evidence']}
        conditions=['1=1'];params=[]
        for field in ('world','plane','perspective'):
            if getattr(request,field)!='all':
                conditions.append(f'a.{field}=?');params.append(getattr(request,field))
        scope=' AND '.join(conditions)
        gate='EXISTS(SELECT 1 FROM delivery_receipts r WHERE r.recipient_id=? AND r.item_type=? AND r.item_id={item} AND r.received_at<=? AND r.recorded_at<=?)'
        # Parent is scope metadata only: no lifecycle projection and no receipt
        # inference from delivery of this passage to delivery of its parent.
        sql="SELECT a.world,a.plane,a.perspective,a.valid_from,a.valid_to,p.value FROM assertions a,json_each(a.payload,'$.evidence') p WHERE "+scope+" AND a.valid_from<=? AND (a.valid_to IS NULL OR a.valid_to>?) AND json_extract(p.value,'$.recorded_at')<=? AND "+gate.format(item="json_extract(p.value,'$.id')")+' ORDER BY a.id,p.key'
        for record in self._db.execute(sql,[*params,valid,valid,known,recipient,'evidence',received_by,known]):
            evidence=json.loads(record['value'])
            if evidence['id'] in attached:
                continue
            rows.append(self._item(record,'evidence',evidence['id'],evidence['title'],'source passage',evidence['text'],evidence['recorded_at'],evidence=[evidence]))
        explicit_notice=bool(NOTICE_WORDS & set(re.findall(r'[^\W_]+',request.query.casefold())))
        if explicit_notice:
            # Notices describe changes, so neither parent validity nor event
            # effective time restricts their availability. The date is returned.
            sql='SELECT a.world,a.plane,a.perspective,a.valid_from,a.valid_to,e.payload FROM assertions a JOIN events e ON e.assertion_id=a.id WHERE '+scope+' AND e.recorded_at<=? AND '+gate.format(item='e.id')+' ORDER BY e.id'
            attached_events={e['id'] for row in rows for e in row['events']}
            for record in self._db.execute(sql,[*params,known,recipient,'event',received_by,known]):
                event=json.loads(record['payload'])
                if event['id'] in attached_events:
                    continue
                rows.append(self._item(record,'event',event['id'],event['source'],'lifecycle notice',event['reason'],event['recorded_at'],summary=f"Effective at {event['effective_at']}",events=[event]))
        return sorted(rows,key=lambda row:row['id'])

    @staticmethod
    def _item(record,kind,item_id,subject,predicate,text,recorded_at,*,summary='',evidence=None,events=None):
        return {'id':f'item:{kind}:{item_id}','item_type':kind,'item_id':item_id,
                'subject':subject,'predicate':predicate,'object':text,'summary':summary,
                'world':record['world'],'plane':record['plane'],'perspective':record['perspective'],
                'valid_from':record['valid_from'],'valid_to':record['valid_to'],
                'recorded_at':recorded_at,'effective_valid_to':None,'status':'available_item',
                'evidence':evidence or [],'events':events or [],'score':0.0,
                'score_breakdown':{'lexical':0.0,'vector':0.0,'graph':0.0},
                'explanation':'Received standalone item; parent claim delivery, active status, and endorsement are not inferred.'}
