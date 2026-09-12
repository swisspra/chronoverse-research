import datetime
import json
from collections import defaultdict

def normalize(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        dt = datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def format_utc(dt):
    return dt.isoformat(timespec='microseconds').replace('+00:00', 'Z') if dt is not None else None


def project(ledger, query):
    v_at = normalize(query['scope']['valid_at'])
    k_at = normalize(query['scope']['known_at'])
    r_by = normalize(query['scope']['received_by'])
    q_world, q_plane, q_persp = query['scope']['world'], query['scope']['plane'], query['scope']['perspective']
    inc_ret = query['scope'].get('include_retired', False)
    recipient = query['recipient_id']

    ids = {'assertion': set(), 'evidence': set(), 'event': set(), 'receipt': set()}
    all_items = {'assertion': {}, 'evidence': {}, 'event': {}}
    
    for a in ledger.get('assertions', []):
        if a['id'] in ids['assertion']: raise ValueError(f"Duplicate assertion id: {a['id']}")
        ids['assertion'].add(a['id'])
        all_items['assertion'][a['id']] = a
        for i, ev in enumerate(a.get('evidence', [])):
            ev_id = ev.get('id', f"{a['id']}-e{i+1}")
            if ev_id in ids['evidence']: raise ValueError(f"Duplicate evidence id: {ev_id}")
            ids['evidence'].add(ev_id)
            all_items['evidence'][ev_id] = {**ev, 'id': ev_id, 'parent_id': a['id']}

    for ev in ledger.get('evidence', []):
        ev_id = ev['id']
        if ev_id in ids['evidence']: raise ValueError(f"Duplicate evidence id: {ev_id}")
        ids['evidence'].add(ev_id)
        all_items['evidence'][ev_id] = ev

    for e in ledger.get('events', []):
        if e['id'] in ids['event']: raise ValueError(f"Duplicate event id: {e['id']}")
        ids['event'].add(e['id'])
        all_items['event'][e['id']] = e

    receipts = defaultdict(list)
    for r in ledger.get('receipts', []):
        if r['id'] in ids['receipt']: raise ValueError(f"Duplicate receipt id: {r['id']}")
        ids['receipt'].add(r['id'])
        if r['item_type'] not in all_items or r['item_id'] not in all_items[r['item_type']]:
            raise ValueError(f"Unknown receipt reference: {r['item_type']} {r['item_id']}")
        rec_at, rcd_at = normalize(r['received_at']), normalize(r['recorded_at'])
        if rcd_at < rec_at: raise ValueError("Receipt logged before received")
        if r['recipient_id'] == recipient and rcd_at <= k_at and rec_at <= r_by:
            receipts[(r['item_type'], r['item_id'])].append(r)

    def is_visible(itype, iid, item_recorded_at):
        return normalize(item_recorded_at) <= k_at and (itype, iid) in receipts

    def scope_match(item):
        return all(q == 'all' or item[k] == q for k, q in [('world', q_world), ('plane', q_plane), ('perspective', q_persp)])

    res_assertions, res_evidence, res_events = [], [], []

    for a_id, a in all_items['assertion'].items():
        if not is_visible('assertion', a_id, a['recorded_at']): continue
        v_from, v_to = normalize(a['valid_from']), normalize(a.get('valid_to'))
        in_validity = v_at >= v_from and (v_to is None or v_at < v_to)
        
        a_events = [e for e in all_items['event'].values() if e['assertion_id'] == a_id and is_visible('event', e['id'], e['recorded_at'])]
        def event_key(e):
            prio = {'supersede': 0, 'correct': 1, 'retract': 2}.get(e['type'], 3)
            return (normalize(e['effective_at']), prio, normalize(e['recorded_at']), e['id'])
        
        a_events.sort(key=event_key)
        status, eff_v_to = 'active', v_to
        for e in a_events:
            eff_at = normalize(e['effective_at'])
            if e['type'] == 'supersede':
                if eff_v_to is None or eff_at < eff_v_to: eff_v_to = eff_at
            if eff_at <= v_at:
                status = {'supersede': 'superseded', 'correct': 'corrected', 'retract': 'retracted'}.get(e['type'], status)

        if scope_match(a) and in_validity:
            if inc_ret or (status == 'active' and (eff_v_to is None or v_at < eff_v_to)):
                a_ev = [ev for ev in all_items['evidence'].values() if ev['parent_id'] == a_id and is_visible('evidence', ev['id'], ev['recorded_at'])]
                res_assertions.append({
                    "id": a_id, "status": status, "effective_valid_to": format_utc(eff_v_to),
                    "evidence": sorted(a_ev, key=lambda x: x['id']), "events": sorted(a_events, key=lambda x: (normalize(x['recorded_at']), x['id']))
                })

    for ev_id, ev in all_items['evidence'].items():
        if not is_visible('evidence', ev_id, ev['recorded_at']): continue
        parent = all_items['assertion'].get(ev['parent_id'])
        if parent and scope_match(parent):
            v_f, v_t = normalize(parent['valid_from']), normalize(parent.get('valid_to'))
            if v_at >= v_f and (v_t is None or v_at < v_t):
                res_evidence.append({"id": ev_id, "parent_id": ev['parent_id'], "text": ev['text'], "title": ev.get('title')})

    for e_id, e in all_items['event'].items():
        if not is_visible('event', e_id, e['recorded_at']): continue
        parent = all_items['assertion'].get(e['assertion_id'])
        if parent and scope_match(parent):
            res_events.append({"id": e_id, "assertion_id": e['assertion_id'], "type": e['type'], "effective_at": format_utc(normalize(e['effective_at']))})

    return {"assertions": sorted(res_assertions, key=lambda x: x['id']), "evidence": sorted(res_evidence, key=lambda x: x['id']), "events": sorted(res_events, key=lambda x: x['id'])}
