"""Read-only second implementation of v3 support and receipt-leak accounting.

Does not import the Store, adapters, scoring/aggregate functions, or reference.
It audits saved top-five contexts against fixture gold and individual receipts;
it does not independently rerun embedding ranking or lifecycle projection.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def digest(value):return hashlib.sha256(value).hexdigest()


def instant(value):
    value=str(value)
    if len(value)==10:value+='T00:00:00+00:00'
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def independently_measure(rows):
    n=len(rows);answerable=[r for r in rows if r['gold']];empty=[r for r in rows if not r['gold']]
    found=sum(len(r['found']) for r in rows);gold=sum(len(r['gold']) for r in rows);returned=sum(r['returned'] for r in rows)
    fraction=lambda numerator,denominator:numerator/denominator if denominator else None
    return {'query_count':n,'answerable_queries':len(answerable),'empty_queries':len(empty),
        'support_precision':fraction(found,returned),'support_recall':fraction(found,gold),
        'complete_support_rate':fraction(sum(r['found']==r['gold'] for r in answerable),len(answerable)),
        'exact_support_set_rate':fraction(sum(r['found']==r['gold'] and r['returned']==len(r['found']) for r in rows),n),
        'empty_abstention_rate':fraction(sum(r['returned']==0 for r in empty),len(empty)),
        'false_abstention_rate':fraction(sum(r['returned']==0 for r in answerable),len(answerable)),
        'leakage_query_rate':fraction(sum(bool(r['leaks']) for r in rows),n),
        'unreceived_items_returned':sum(len(r['leaks']) for r in rows),
        'supported_units_returned':found,'gold_support_units':gold,'returned_context_units':returned}


def verify(directory,fixture_path):
    directory=Path(directory);summary=json.loads((directory/'summary.json').read_text());loaded={}
    for name,artifact in summary['raw_artifacts'].items():
        encoded=(directory/artifact['path']).read_bytes();raw=gzip.decompress(encoded)
        assert digest(encoded)==artifact['gzip_sha256'],f'{name}: compressed hash'
        assert digest(raw)==artifact['uncompressed_sha256'],f'{name}: original hash'
        assert len(raw)==artifact['uncompressed_bytes'] and len(encoded)==artifact['compressed_bytes'],f'{name}: size'
        loaded[name]=json.loads(raw)
    result=loaded['results.json'];contexts=loaded['retrieval-contexts.json']
    assert summary['original_result_provenance']==result['provenance'],'measurement provenance'
    encoded=Path(fixture_path).read_bytes();raw=gzip.decompress(encoded) if Path(fixture_path).suffix=='.gz' else encoded
    assert digest(encoded)==result['fixture_sha256'],'fixture compressed hash'
    assert digest(raw)==result['fixture_raw_sha256'],'fixture original hash'
    fixture=json.loads(raw);queries={q['id']:q for q in fixture['queries']}
    assert result['status']=='complete' and len(queries)==len(fixture['queries'])
    assert result['query_manifest']==fixture['queries'],'query manifest'
    assert contexts['query_manifest']==result['query_manifest'],'context manifest'
    assert contexts['fixture_sha256']==result['fixture_sha256'],'context fixture'
    assertions={a['id']:a for a in fixture['assertions']};evidence={};events={e['id']:e for e in fixture['events']};owners={};source_times={}
    for aid,a in assertions.items():
        source_times[('assertion',aid)]=instant(a['recorded_at'])
        for index,e in enumerate(a['evidence'],1):
            eid=e.get('id') or f'{aid}-e{index}'
            evidence[eid]=e;owners[eid]=aid;source_times[('evidence',eid)]=instant(e.get('recorded_at') or a['recorded_at'])
    source_times.update({('event',eid):instant(e['recorded_at']) for eid,e in events.items()})
    receipts=defaultdict(list)
    for r in fixture['receipts']:
        receipts[(r['recipient_id'],r['item_type'],r['item_id'])].append((instant(r['received_at']),instant(r['recorded_at'])))
    measured={};count=0
    for method,data in result['methods'].items():
        assert set(data['per_query'])==set(queries),f'{method}: query coverage'
        rows={}
        for qid,row in data['per_query'].items():
            q=queries[qid];gold_claims=set(q['gold_assertion_ids']);gold={'assertion:'+aid for aid in gold_claims}
            gold.update('evidence:'+eid for eid in q['gold_evidence_ids'] if owners[eid] not in gold_claims)
            if q.get('kind')=='event':gold.update('event:'+eid for eid in q['gold_event_ids'])
            claims=set();passages=set();notices=set()
            assert len(row['results'])<=5,f'{method}/{qid}: top5'
            for context in row['results']:
                kind=context.get('item_type')
                if not kind:
                    aid=context['id'];claims.add(aid);original=assertions[aid]
                    for field in ('subject','predicate','object','summary','world','plane','perspective'):
                        assert context[field]==original.get(field,''),f'{method}/{qid}: assertion text {field}'
                    for field in ('valid_from','recorded_at'):
                        assert instant(context[field])==instant(original[field]),f'{method}/{qid}: assertion time {field}'
                    assert (instant(context['valid_to']) if context['valid_to'] else None)==(instant(original['valid_to']) if original.get('valid_to') else None),f'{method}/{qid}: original validity'
                for e in context['evidence']:
                    passages.add(e['id'])
                    assert (e['text'],e['title'])==(evidence[e['id']]['text'],evidence[e['id']]['title']),f'{method}/{qid}: evidence text'
                    assert instant(e['recorded_at'])==source_times[('evidence',e['id'])],f'{method}/{qid}: evidence source time'
                for e in context['events']:
                    notices.add(e['id'])
                    for field in ('reason','source','type','assertion_id'):
                        assert e[field]==events[e['id']][field],f'{method}/{qid}: event payload'
                    for field in ('effective_at','recorded_at'):
                        assert instant(e[field])==instant(events[e['id']][field]),f'{method}/{qid}: event time'
                if kind=='evidence':
                    e=evidence[context['item_id']]
                    assert context['subject']==e['title'] and context['object']==e['text'],f'{method}/{qid}: standalone passage'
                elif kind=='event':
                    e=events[context['item_id']]
                    assert context['subject']==e['source'] and context['object']==e['reason'],f'{method}/{qid}: standalone notice'
            found=set()
            for aid in claims & gold_claims:
                if {eid for eid in q['gold_evidence_ids'] if owners[eid]==aid}<=passages:found.add('assertion:'+aid)
            found.update('evidence:'+eid for eid in passages if 'evidence:'+eid in gold)
            found.update('event:'+eid for eid in notices if 'event:'+eid in gold)
            assert row['gold_support']==sorted(gold),f'{method}/{qid}: gold support'
            assert row['found_support']==sorted(found),f'{method}/{qid}: found support'
            assert row['missing_support']==sorted(gold-found),f'{method}/{qid}: missing support'
            returned={('assertion',aid) for aid in claims}|{('evidence',eid) for eid in passages}|{('event',eid) for eid in notices}
            known=instant(q['scope']['known_at']);received_by=instant(q['scope']['received_by'])
            leaks={key for key in returned if source_times[key]>known or not any(delivered<=received_by and recorded<=known for delivered,recorded in receipts[(q['recipient_id'],*key)])}
            assert row['leaks']==[{'type':kind,'id':item} for kind,item in sorted(leaks)],f'{method}/{qid}: receipt/source leakage'
            rows[qid]={'gold':gold,'found':found,'returned':len(row['results']),'leaks':leaks};count+=1
        assert data['metrics']==independently_measure(list(rows.values())),f'{method}: overall metrics'
        for field in ('split','family','kind'):
            groups=defaultdict(list)
            for qid,value in rows.items():groups[queries[qid].get(field,'unspecified')].append(value)
            assert data['by_'+field]=={name:independently_measure(values) for name,values in sorted(groups.items())},f'{method}: {field} metrics'
        assert data['stability']['matching_repeated_signatures']==data['stability']['comparisons']==len(queries),f'{method}: stability'
        assert summary['methods'][method]=={k:v for k,v in data.items() if k!='per_query'},f'{method}: packaged summary'
        measured[method]=rows
    for arm,method in [('D_post_projection_receipts','Filter after projection'),('E_delivery_explicit_item_view','Delivery explicit item view')]:
        assert contexts['arms'][arm]=={qid:row['results'] for qid,row in result['methods'][method]['per_query'].items()},f'{arm}: context identity'
    return {'status':'verified','verified_method_queries':count,'test_queries':sum(q['split']=='test' for q in queries.values()),
            'source_result_sha256':summary['raw_artifacts']['results.json']['uncompressed_sha256'],
            'scope':'Second implementation recomputes saved top5 support/leak accounting from fixture gold, original source text, and per-item receipts. It does not rerun model ranking or reconstruct lifecycle candidates.'}


def verify_sufficiency(directory):
    import subprocess
    directory=Path(directory)
    raw=gzip.decompress((directory/'results.json.gz').read_bytes())
    result=json.loads(raw);gate_bytes=(directory/'frozen-dev-gate.json').read_bytes();gate=json.loads(gate_bytes)
    evaluation=json.loads((directory/'sufficiency-test.json').read_text())
    assert digest(raw)==gate['source_result_sha256']==evaluation['source_result_sha256'],'gate source hash'
    assert digest(gate_bytes)==evaluation['frozen_gate_sha256'],'frozen gate hash'
    committed=subprocess.check_output(['git','show',evaluation['frozen_gate_commit']+':docs/benchmarks-delivery-v3/frozen-dev-gate.json'],cwd=ROOT)
    assert committed==gate_bytes,'committed gate bytes'
    queries=[q for q in result['query_manifest'] if q['split']=='test'];count=0
    def scored(row,selected):
        returned=set()
        for context in selected:
            if not context.get('item_type'):returned.add('assertion:'+context['id'])
            returned.update('evidence:'+e['id'] for e in context['evidence'])
            returned.update('event:'+e['id'] for e in context['events'])
        return {'gold':set(row['gold_support']),'found':set(row['found_support'])&returned,
                'returned':len(selected),'leaks':{(e['type'],e['id']) for e in row['leaks'] if e['type']+':'+e['id'] in returned}}
    def metrics(rows):
        m=independently_measure(rows);precision=m['support_precision'] or 0;recall=m['support_recall'] or 0
        m['micro_f0.5']=1.25*precision*recall/(.25*precision+recall) if precision+recall else 0.
        m['answerable_coverage']=1-(m['false_abstention_rate'] or 0.)
        return m
    for method,data in result['methods'].items():
        chosen=gate['methods'][method]['chosen'];absolute=chosen['absolute_cosine'];margin=chosen['relative_margin']
        actual=evaluation['methods'][method];before={};after={}
        assert actual['frozen_gate']=={'absolute_cosine':absolute,'relative_margin':margin},f'{method}: gate values'
        for q in queries:
            row=data['per_query'][q['id']];candidates=row['results']
            ceiling=max((c['score_breakdown']['vector'] for c in candidates),default=-1)
            kept=[c for c in candidates if c['score_breakdown']['vector']>=absolute and c['score_breakdown']['vector']>=ceiling-margin]
            before[q['id']]=scored(row,candidates);after[q['id']]=scored(row,kept);count+=1
        assert actual['before']==metrics(list(before.values())),f'{method}: before metrics'
        assert actual['after']==metrics(list(after.values())),f'{method}: after metrics'
        for family,values in actual['per_family'].items():
            subset=[q['id'] for q in queries if q['family']==family]
            assert values['before']==metrics([before[qid] for qid in subset]),f'{method}: family before'
            assert values['after']==metrics([after[qid] for qid in subset]),f'{method}: family after'
    assert evaluation['test_queries']==len(queries)
    return {'verified_test_method_queries':count,'frozen_gate_commit':evaluation['frozen_gate_commit'],
            'source_result_sha256':digest(raw),'scope':'Saved rounded cosine gates and metrics recomputed without importing the calibration/evaluation implementation; committed gate bytes verified.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path,default=ROOT/'docs/benchmarks-delivery-v3');p.add_argument('--fixture',type=Path,default=ROOT/'benchmarks/data/delivery-v3.json.gz')
    args=p.parse_args();report=verify(args.input_dir,args.fixture)
    if (args.input_dir/'sufficiency-test.json').exists():report['sufficiency']=verify_sufficiency(args.input_dir)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
