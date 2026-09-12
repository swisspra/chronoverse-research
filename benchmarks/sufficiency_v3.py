"""DEV-only gate calibration, followed by a separately invoked frozen TEST evaluation."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from benchmarks.delivery_v3 import aggregate
from benchmarks.provenance import BenchmarkRun,sha256

ABSOLUTE=[.20,.30,.40,.50,.60,.70,.80]
MARGIN=[.02,.05,.10,.20,1.00]
MIN_COVERAGE=.60
ROOT=Path(__file__).resolve().parents[1]


def gate_row(row,absolute,margin):
    value=deepcopy(row);best=max((r['score_breakdown']['vector'] for r in row['results']),default=-1)
    value['results']=[r for r in row['results'] if r['score_breakdown']['vector']>=absolute and r['score_breakdown']['vector']>=best-margin]
    returned=set()
    for r in value['results']:
        if not r.get('item_type'):returned.add('assertion:'+r['id'])
        returned.update('evidence:'+e['id'] for e in r['evidence'])
        returned.update('event:'+e['id'] for e in r['events'])
    found=returned&set(row['found_support']);value['found_support']=sorted(found);value['missing_support']=sorted(set(row['gold_support'])-found)
    value['leaks']=[item for item in row['leaks'] if item['type']+':'+item['id'] in returned]
    return value


def summarize(rows):
    metrics=aggregate(rows);p=metrics['support_precision'] or 0;r=metrics['support_recall'] or 0
    metrics['micro_f0.5']=1.25*p*r/(.25*p+r) if p+r else 0.
    metrics['answerable_coverage']=1-(metrics['false_abstention_rate'] or 0.)
    return metrics


def calibrate(result):
    dev_ids=[q['id'] for q in result['query_manifest'] if q['split']=='dev']
    if not dev_ids:raise ValueError('DEV set required')
    output={}
    for method,data in result['methods'].items():
        dev={qid:data['per_query'][qid] for qid in dev_ids};grid=[]
        for absolute in ABSOLUTE:
            for margin in MARGIN:
                grid.append({'absolute_cosine':absolute,'relative_margin':margin,'dev_metrics':summarize({qid:gate_row(row,absolute,margin) for qid,row in dev.items()})})
        feasible=[g for g in grid if g['dev_metrics']['answerable_coverage']>=MIN_COVERAGE]
        # Frozen objective and tie-breaks copied from the v2 gate protocol.
        chosen=max(feasible or grid,key=lambda g:(g['dev_metrics']['micro_f0.5'],g['dev_metrics']['support_recall'] or 0,g['dev_metrics']['support_precision'] or 0,-g['absolute_cosine'],g['relative_margin']))
        output[method]={'chosen':chosen,'coverage_constraint_met':bool(feasible),'grid':grid}
    return {'status':'calibrated_dev_only','dev_query_ids':dev_ids,'methods':output,
            'protocol':'Maximize DEV micro F0.5 subject to answerable coverage>=.60. Tie-break recall, precision, lower absolute cosine, larger margin. No reranking.',
            'input_pool':'Recorded top5; vector components are rounded to4decimals by the unchanged Store. No claims about rejected candidates outside top5.'}


def evaluate(result,frozen):
    test=[q for q in result['query_manifest'] if q['split']=='test'];output={}
    for method,data in result['methods'].items():
        chosen=frozen['methods'][method]['chosen'];rows={q['id']:data['per_query'][q['id']] for q in test}
        gated={qid:gate_row(row,chosen['absolute_cosine'],chosen['relative_margin']) for qid,row in rows.items()}
        output[method]={'frozen_gate':{k:chosen[k] for k in ('absolute_cosine','relative_margin')},'before':summarize(rows),'after':summarize(gated),
            'per_family':{family:{'before':summarize({q['id']:rows[q['id']] for q in test if q['family']==family}),
                                  'after':summarize({q['id']:gated[q['id']] for q in test if q['family']==family})} for family in sorted({q['family'] for q in test})}}
    return {'status':'complete','test_queries':len(test),'methods':output,'production_change':False,
            'limitations':['DEV and TEST entities and scenario variants are disjoint; parent mechanisms are shared.','Top5 gating cannot recover missing evidence. Cosine is not a truth probability.','Representative uploaded documents have not validated this gate; production defaults remain unchanged.']}


def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['calibrate','evaluate'],required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--gate',type=Path,required=True);p.add_argument('--output',type=Path);p.add_argument('--allow-dirty',action='store_true');args=p.parse_args()
    run=BenchmarkRun(allow_dirty=args.allow_dirty,sources=[Path(__file__),ROOT/'benchmarks/delivery_v3.py',ROOT/'benchmarks/provenance.py'])
    source_hash=sha256(args.input);data=json.loads(args.input.read_text())
    if data['status']!='complete':raise ValueError('Complete retrieval run required')
    if args.stage=='calibrate':
        result=calibrate(data);result['source_result_sha256']=source_hash;run.write_json(args.gate,result)
    else:
        if not args.output:raise ValueError('--output required for evaluate')
        frozen=json.loads(args.gate.read_text());gate_hash=sha256(args.gate)
        if frozen['source_result_sha256']!=source_hash:raise ValueError('Gate belongs to a different retrieval run')
        relative=args.gate.resolve().relative_to(ROOT).as_posix()
        commit=subprocess.check_output(['git','log','-1','--format=%H','--',relative],cwd=ROOT,text=True).strip()
        if not commit:raise ValueError('Commit the frozen DEV gate before evaluating TEST')
        import hashlib
        committed=subprocess.check_output(['git','show',f'{commit}:{relative}'],cwd=ROOT)
        if hashlib.sha256(committed).hexdigest()!=gate_hash:raise ValueError('Frozen gate differs from committed bytes')
        result=evaluate(data,frozen);result.update(source_result_sha256=source_hash,frozen_gate_sha256=gate_hash,frozen_gate_commit=commit);run.write_json(args.output,result)
    print(json.dumps({'status':result['status'],'methods':len(result['methods'])}))

if __name__=='__main__':main()
