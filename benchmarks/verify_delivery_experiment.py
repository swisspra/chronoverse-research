"""Second implementation in this repository; no scoring/projection imports."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/benchmarks-delivery'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clock(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def verify(directory=OUT):
    directory=Path(directory)
    result=json.loads((directory/'results.json').read_text());fixture=result['fixture'];queries=fixture['queries']
    assert result['status']=='complete'
    assert sha(ROOT/'benchmarks/data/delivery-v1.json')==result['fixture_sha256']==sha(directory/'fixture.json')
    assert fixture==json.loads((directory/'fixture.json').read_text())
    assert len(queries)==len({(q['recipient_id'],q['query'],json.dumps(q['scope'],sort_keys=True)) for q in queries})==50
    if result.get('migration'):
        manifest=json.loads((directory/'migration-manifest.json').read_text())
        assert sha(directory/'results.json')==manifest['files']['results']['new_sha256']
        assert sha(directory/'fixture.json')==manifest['files']['fixture']['new_sha256']
        historical=ROOT/'docs/benchmarks-observer'
        for kind in ('results','fixture'):
            assert sha(historical/(kind+'.json'))==manifest['files'][kind]['old_sha256']
        original=json.loads((historical/'results.json').read_text())
        assert original['source_sha256']==result['source_sha256']
        for name,digest in result['source_sha256'].items():
            assert sha(historical/'source'/name)==digest
        for label,method in original['methods'].items():
            current=result['methods']['Delivery projection' if label=='Observer projection' else label]
            assert current['metrics']==method['metrics'] and current['latency']==method['latency']
            assert set(current['per_query'])==set(method['per_query'])
            for qid,row in method['per_query'].items():
                for field in ('results','seconds','gold_support','found_support','missing_support','leaks','candidate_projection'):
                    assert current['per_query'][qid][field]==row[field]
    else:
        for name,digest in result['source_sha256'].items():
            assert sha(directory/'source'/name)==digest
    source={};parent={}
    for assertion in fixture['assertions']:
        source[('assertion',assertion['id'])]=clock(assertion['recorded_at'])
        for index,evidence in enumerate(assertion['evidence'],1):
            eid=assertion['id']+f'-e{index}';parent[eid]=assertion['id']
            source[('evidence',eid)]=clock(evidence.get('recorded_at') or assertion['recorded_at'])
    source.update({('event',e['id']):clock(e['recorded_at']) for e in fixture['events']})
    for label,method in result['methods'].items():
        rows=method['per_query'];assert set(rows)=={q['id'] for q in queries}
        counts=Counter()
        for query in queries:
            row=rows[query['id']];records=row['results'];scope=query['scope']
            assert len(records)<=5 and len({r['id'] for r in records})==len(records)
            visible={(r['item_type'],r['item_id']) for r in fixture['receipts']
                     if r['recipient_id']==query['recipient_id'] and clock(r['received_at'])<=clock(scope['received_by'])
                     and clock(r['recorded_at'])<=clock(scope['known_at'])
                     and source[(r['item_type'],r['item_id'])]<=clock(scope['known_at'])}
            returned={('assertion',r['id']) for r in records}
            evidence={e['id'] for r in records for e in r['evidence']}
            returned.update(('evidence',eid) for eid in evidence)
            returned.update(('event',e['id']) for r in records for e in r['events'])
            leaked=returned-visible
            assert leaked=={(r['type'],r['id']) for r in row['leaks']}
            targets={'assertion:'+aid for aid in query['gold_assertion_ids']}
            targets.update('evidence:'+eid for eid in query['gold_evidence_ids'] if parent[eid] not in query['gold_assertion_ids'])
            actual=set()
            for record in records:
                aid=record['id']
                if aid in query['gold_assertion_ids']:
                    required={eid for eid in query['gold_evidence_ids'] if parent[eid]==aid}
                    if required<=evidence:actual.add('assertion:'+aid)
            actual.update('evidence:'+eid for eid in evidence if 'evidence:'+eid in targets)
            assert targets==set(row['gold_support']) and actual==set(row['found_support'])
            assert targets-actual==set(row['missing_support'])
            counts.update(tp=len(actual),expected=len(targets),returned=len(records),leaks=len(leaked),leak_queries=bool(leaked),
                          answerable=bool(targets),empty=not targets,complete=bool(targets) and targets<=actual,
                          false_abstention=bool(targets) and not records,empty_abstention=not targets and not records,
                          exact=targets<=actual and len(records)==len(actual))
        expected_metrics={'query_count':50,'answerable_queries':counts['answerable'],'empty_queries':counts['empty'],
                          'support_precision':counts['tp']/counts['returned'],'support_recall':counts['tp']/counts['expected'],
                          'complete_support_rate':counts['complete']/counts['answerable'],
                          'exact_support_set_rate':counts['exact']/50,'empty_abstention_rate':counts['empty_abstention']/counts['empty'],
                          'false_abstention_rate':counts['false_abstention']/counts['answerable'],
                          'leakage_query_rate':counts['leak_queries']/50,'unreceived_items_returned':counts['leaks'],
                          'supported_units_returned':counts['tp'],'gold_support_units':counts['expected'],'returned_assertion_contexts':counts['returned']}
        assert expected_metrics.keys()==method['metrics'].keys()
        for key,value in expected_metrics.items():assert abs(value-method['metrics'][key])<1e-12,(label,key)
    sql=result['methods']['Ordinary SQL receipt filter']['per_query'];delivery=result['methods']['Delivery projection']['per_query']
    for qid,row in sql.items():
        assert row['results']==delivery[qid]['results']
        assert row['candidate_projection']==delivery[qid]['candidate_projection']
    orphan=delivery['oq41'];assert orphan['gold_support']==['evidence:tu6h-e1'] and orphan['found_support']==[]
    audit={'status':'passed','result_sha256':sha(directory/'results.json'),'fixture_sha256':result['fixture_sha256'],
           'checks':['50 unique fixed query scopes; no padded duplicates','250 method/query outcomes recalculated by a second implementation in this repository',
                     'Receipt AND source recording cutoffs recalculated for every returned item',
                     '50/50 full SQL and delivery result/projection payloads identical','Standalone evidence-only gold counted as answerable and missed',
                     'Archived execution source hashes and schema-migration hashes verified; current source is not presented as historical execution']}
    return audit


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-dir',type=Path,default=OUT)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    audit=verify(args.input_dir)
    if args.output:args.output.write_text(json.dumps(audit,indent=2)+'\n')
    print(json.dumps(audit,indent=2))


if __name__=='__main__':main()
