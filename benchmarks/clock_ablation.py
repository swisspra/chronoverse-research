"""Fixed-pool clock ablation preparation only; no model or API calls."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path

from benchmarks.answer_contexts import ROOT, catalog, candidate_inventory, load, query_input, scoring_metadata, serialize_context
from benchmarks.answer_experiment import PROMPT
from benchmarks.provenance import BenchmarkRun, add_provenance_argument, sha256

MODES={'FULL':(True,True,True),'VK':(True,True,False),'V':(True,False,False),'NONE':(False,False,False)}


def instant(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    return (parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def project_units(fixture,query,pool,mode):
    """Independently defined gates; fixed ranked pool, never a Store/gold oracle."""
    valid_gate,known_gate,receipt_gate=MODES[mode]
    assertions,items,owners,receipts=catalog(fixture)
    parents={a['id']:a for a in assertions};units={u['id']:u for u in candidate_inventory(fixture)}
    scope=query['scope'];known=instant(scope['known_at']);valid=instant(scope['valid_at']);delivery=instant(scope['received_by'])
    def available(typed):
        value=items[typed]
        if known_gate and instant(value['recorded_at'])>known:return False
        if receipt_gate and not any(instant(r['received_at'])<=delivery and (not known_gate or instant(r['recorded_at'])<=known)
            for r in receipts.get((query['recipient_id'],typed),[])):return False
        return True
    def matches(parent):return all(scope.get(k,'all')=='all' or parent[k]==scope[k] for k in ('world','plane','perspective'))
    def interval(a):return not valid_gate or (instant(a['valid_from'])<=valid and (a.get('valid_to') is None or valid<instant(a['valid_to'])))
    def active(a):
        if not valid_gate:return True
        if not interval(a):return False
        return not any(e['assertion_id']==a['id'] and e['type'] in ('supersede','correct','retract') and instant(e['effective_at'])<=valid and available('event:'+e['id']) for e in fixture['events'])
    selected=[];rows=[]
    for typed in pool:
        kind,id=typed.split(':',1);value=items[typed]
        parent=value if kind=='assertion' else parents[owners[id] if kind=='evidence' else value['assertion_id']]
        if not matches(parent) or not available(typed) or (kind=='assertion' and not active(value)):continue
        if kind=='evidence' and not interval(parent):continue
        unit=deepcopy(units[typed]['rows'])
        if kind=='assertion':
            unit[0]['evidence']=[e for e in unit[0]['evidence'] if available('evidence:'+e['id'])]
            # Only notices independently ranked in the raw pool enter context.
        rows.extend(unit);selected.append(typed)
        if len(selected)==5:break
    # All variants retain the same raw receipt metadata for included items so
    # the shared prompt can enforce clocks; only item selection is ablated.
    return serialize_context(rows,[],query,receipts,bounded_receipts=False),selected


def build(fixture,manifest):
    by_id={q['id']:q for q in fixture['queries']};_,items,owners,receipts=catalog(fixture)
    rows=[];trace={}
    for qid in manifest['selected_query_ids']:
        q=by_id[qid];public=query_input(q);pool=manifest['trace'][qid]['dense_top50']
        if len(pool)!=50 or len(set(pool))!=50:raise ValueError('Frozen pool must contain exactly 50 distinct typed items.')
        contexts={mode:project_units(fixture,public,pool,mode) for mode in MODES}
        metadata=scoring_metadata(q,items,owners,receipts)
        for mode,(context,selected) in contexts.items():
            rows.append({'query_id':qid,'arm':mode,'question':public['question'],'recipient_id':public['recipient_id'],
                **{k:public['scope'][k] for k in ('valid_at','known_at','received_by')},
                'context':context,'prompt_sha256':sha256(PROMPT),**metadata})
            trace.setdefault(qid,{})[mode]=selected
    return rows,trace


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    parser.add_argument('--fixture',type=Path,default=ROOT/'benchmarks/data/delivery-v3.json.gz')
    parser.add_argument('--source-manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/benchmarks-next/clock-contexts-50.jsonl.gz')
    args=parser.parse_args();run=BenchmarkRun(allow_dirty=args.allow_dirty)
    inputs={p:sha256(p) for p in (args.fixture,args.source_manifest,PROMPT)}
    fixture=load(args.fixture);manifest=load(args.source_manifest)
    if manifest['fixture_sha256']!=inputs[args.fixture] or manifest['prompt_sha256']!=inputs[PROMPT]:raise ValueError('Frozen fixture/prompt hash mismatch.')
    rows,trace=build(fixture,manifest)
    raw=''.join(json.dumps(r,sort_keys=True,ensure_ascii=False)+'\n' for r in rows).encode()
    if any(sha256(p)!=value for p,value in inputs.items()):raise RuntimeError('Ablation source inputs changed.')
    receipt=run.write_bytes(args.output,gzip.compress(raw,mtime=0))
    run.write_json(args.output.with_suffix('.manifest.json'),{'status':'prepared; no inference','rows':len(rows),'queries':len(manifest['selected_query_ids']),
        'modes':MODES,'prompt_sha256':inputs[PROMPT],'fixture_sha256':inputs[args.fixture],
        'source_manifest_sha256':inputs[args.source_manifest],'uncompressed_sha256':hashlib.sha256(raw).hexdigest(),
        'storage':receipt,'trace':trace,'protocol':'Fixed MiniLM top50 pool; first5 eligible units. No clocks alter rank/text/model/prompt. Decompress JSONL before harness use.'})


if __name__=='__main__':main()
