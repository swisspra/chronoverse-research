"""One amended continuation of the fixed pilot; prepare-only unless --mode run.

Original responses are opaque retained values. This driver audits transport, not
answer quality, and never retries any original or uncertain request.
"""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess

from benchmarks import answer_experiment as harness
from benchmarks.provenance import BenchmarkRun

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL_SHA='547c173cebac53cc59e4f673b73b0fe3dedd98603e11a2c9557833cc8216c7c8'
ORIGINAL_RUN_ID='20e4ca5f21e13a68e1d92f8b7a522093cc65d94a5e89c79bf00b98ec0c5e0dc6'
ORIGINAL_SOURCE_COMMIT='9ece9b9'
REPAIRED_SOURCE_COMMIT='e77c0d7'
AMENDMENT_COMMIT='009f732'
UNCERTAIN_ID='a8879e9f8946a324aab53128227ea1928ac2232425b3e2230e6feed4cc1445cd'
MANIFEST_SHA='e807eacb8b49a965f1c53257a7903d9006f122b1cc7facc935e5798988e872ce'
PROMPT_SHA='3bb012d59e1a712665f130637fd1c38c7d406d53d0bba5751039bf530ed7b497'
MODEL='vertex_ai/gemini-3.8-flash'
WHOLE_INPUT=6737967
WHOLE_OUTPUT=768000


def require(ok,message):
    if not ok:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()


def numeric(value):return type(value) in (int,float) and math.isfinite(value) and value>=0


def usage_valid(usage,request):
    return (isinstance(usage,dict) and all(numeric(usage.get(k)) for k in ('prompt_tokens','completion_tokens','total_tokens'))
        and usage['prompt_tokens']<=request['input_reservation'] and usage['completion_tokens']<=request['output_reservation']
        and usage['total_tokens']<=request['input_reservation']+request['output_reservation'])


def validate_record(record,request,*,allow_original_timeout=False):
    for key in ('id','query_id','arm','repeat','input_reservation','output_reservation'):
        require(record.get(key)==request[key],'Request slot/reservation mismatch: '+key)
    require(not record.get('budget_breach') and not record.get('model_guard_failure') and not record.get('usage_guard_failure'),'Guarded prior response.')
    require(numeric(record.get('seconds')),'Invalid transport latency.')
    if allow_original_timeout and request['id']==UNCERTAIN_ID:
        require(record.get('status')=='uncertain' and record.get('error_type')=='TimeoutError','Pinned timeout changed.')
        require('usage' not in record and 'raw_answer' not in record and 'returned_model' not in record,'Do not reconstruct the timeout outcome.')
        return
    require(record.get('status') in ('complete','truncated_or_invalid'),'Only terminal responses may continue.')
    require(record.get('finish_reason') in ('stop','length'),'Unexpected terminal finish reason.')
    require((record['status']=='complete')==(record['finish_reason']=='stop'),'Status/finish mismatch.')
    require(record.get('returned_model')==MODEL,'Actual response model mismatch.')
    require(isinstance(record.get('raw_answer'),str),'Missing retained response value.')
    require(usage_valid(record.get('usage'),request),'Missing/nonnumeric/excess provider usage.')


def build_plan(original_raw,manifest_raw,prompt_raw):
    require(sha(original_raw)==ORIGINAL_SHA,'Original checkpoint hash mismatch.')
    require(sha(manifest_raw)==MANIFEST_SHA and sha(prompt_raw)==PROMPT_SHA,'Captured manifest/prompt hash mismatch.')
    original=json.loads(original_raw);rows=[json.loads(line) for line in manifest_raw.decode().splitlines() if line.strip()]
    requests,estimate=harness.prepare(rows,prompt_raw.decode(),MODEL,max_input_tokens=8192,long_max_input_tokens=16384,max_completion_tokens=1024)
    estimate.update(usd_reservation=None,pricing='Proxy pricing unknown; no USD estimate claimed')
    require(len(rows)==250 and estimate['queries']==50 and len(requests)==750,'Frozen pilot shape changed.')
    require(estimate['input_token_reservation']==WHOLE_INPUT and estimate['output_token_reservation']==WHOLE_OUTPUT,'Whole-plan reservation changed.')
    require(original.get('run_id')==ORIGINAL_RUN_ID,'Original run identity mismatch.')
    require(original.get('actual_response_model')==MODEL and original.get('estimate')==estimate,'Original model/estimate mismatch.')
    records=original.get('requests',{})
    require(isinstance(records,dict) and list(records)==[r['id'] for r in requests[:647]],'Original records are not the exact planned prefix.')
    require(requests[646]['id']==UNCERTAIN_ID,'Timeout is not the original terminal prefix slot.')
    for request in requests[:647]:validate_record(records[request['id']],request,allow_original_timeout=True)
    require(Counter(r['status'] for r in records.values())==Counter(complete=533,truncated_or_invalid=113,uncertain=1),'Original transport counts changed.')
    remaining=requests[647:];subset=copy.deepcopy(estimate)
    subset.update(requests=len(remaining),input_token_reservation=sum(r['input_reservation'] for r in remaining),output_token_reservation=sum(r['output_reservation'] for r in remaining))
    return dict(original=original,rows=rows,requests=requests,remaining=remaining,estimate=estimate,continuation_estimate=subset,original_checkpoint_sha256=sha(original_raw))


def verify_endpoint_identity(plan,base_url):
    """Bind to the original provider without serializing its private URL."""
    harness.safe_endpoint(base_url)
    old_source=subprocess.check_output(['git','show',ORIGINAL_SOURCE_COMMIT+':benchmarks/answer_experiment.py'],cwd=ROOT)
    identity=harness.digest(json.dumps({'requests':plan['requests'],'base_url':base_url,'scoring_metadata':plan['rows'],
        'expected_response_model':MODEL,'harness_sha256':sha(old_source)},sort_keys=True,ensure_ascii=False).encode())
    require(identity==ORIGINAL_RUN_ID,'Provider/request identity differs from original run; no dispatch.')
    repaired=subprocess.check_output(['git','show',REPAIRED_SOURCE_COMMIT+':benchmarks/answer_experiment.py'],cwd=ROOT)
    require(Path(harness.__file__).read_bytes()==repaired,'Execute source differs from the frozen terminal-write repair.')


def dispatch(plan,*,base_url,key,checkpoint,send=harness.transport):
    require(not checkpoint.exists(),'Continuation checkpoint already exists; no implicit replay or resume.')
    verify_endpoint_identity(plan,base_url)
    reservations={sha(canonical(r['body'])):r for r in plan['remaining']}
    observed_failure={}
    def checked_send(endpoint,credential,body,timeout):
        request=reservations.get(sha(canonical(body)))
        require(request is not None,'Unexpected request body; no dispatch.')
        response=send(endpoint,credential,body,timeout)
        usage=response.get('usage')
        numeric_usage=isinstance(usage,dict) and all(numeric(usage.get(k)) for k in ('prompt_tokens','completion_tokens','total_tokens'))
        ordinary_excess=numeric_usage and (usage['prompt_tokens']>request['input_reservation'] or usage['completion_tokens']>request['output_reservation'])
        if not usage_valid(usage,request) and not ordinary_excess:
            choice=(response.get('choices') or [{}])[0]
            observed_failure.update(usage=usage,response_id=response.get('id'),returned_model=response.get('model'),
                finish_reason=choice.get('finish_reason'),raw_answer=choice.get('message',{}).get('content'),
                usage_guard_failure='missing, nonnumeric, or total-only excess usage')
            raise ValueError('Invalid provider usage; stop continuation.')
        # Numeric prompt/output excess reaches execute's original durable guard,
        # retaining the received answer, actual model and measured usage.
        return response
    try:
        return harness.execute(plan['remaining'],plan['rows'],plan['continuation_estimate'],base_url=base_url,key=key,checkpoint=checkpoint,
            max_total_input_tokens=plan['continuation_estimate']['input_token_reservation'],max_total_output_tokens=plan['continuation_estimate']['output_token_reservation'],
            expected_response_model=MODEL,timeout=90,send=checked_send)
    except RuntimeError:
        if observed_failure:
            state=json.loads(checkpoint.read_text())
            last=next(reversed(state['requests'].values()))
            require(last.get('status')=='uncertain','Expected newly stopped uncertain record.')
            last.update(observed_failure)
            harness.atomic_checkpoint(checkpoint,state)
        raise


def artifacts(plan,state):
    require(state.get('actual_response_model')==MODEL,'Continuation actual model mismatch.')
    require(list(state.get('requests',{}))==[r['id'] for r in plan['remaining']],'Continuation is not exactly the103 undispatched requests in order.')
    for request in plan['remaining']:validate_record(state['requests'][request['id']],request)
    bindings=dict(estimate=copy.deepcopy(plan['estimate']),continuation_estimate=copy.deepcopy(plan['continuation_estimate']),
        manifest_sha256=MANIFEST_SHA,prompt_sha256=PROMPT_SHA,expected_response_model=MODEL,actual_response_model=MODEL,
        original_checkpoint_sha256=plan['original_checkpoint_sha256'],original_run_id=ORIGINAL_RUN_ID,
        original_source_commit=ORIGINAL_SOURCE_COMMIT,repaired_execute_commit=REPAIRED_SOURCE_COMMIT,amendment_commit=AMENDMENT_COMMIT,
        continuation_run_id=state['run_id'],original_records_json_sha256=sha(canonical(plan['original']['requests'])),
        unknown_original_request_id=UNCERTAIN_ID,unknown_original_usage=True,private_cost_usd=None)
    continuation=dict(bindings,status='complete',phase='undispatched_only_continuation',requests=copy.deepcopy(state['requests']))
    union=dict(bindings,status='completed_plan_with_uncertainty',phase='original_plus_undispatched_continuation',
        requests=copy.deepcopy(plan['original']['requests'])|copy.deepcopy(state['requests']))
    require(len(union['requests'])==750,'Union does not account for every original slot.')
    return continuation,union


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=('prepare','run'),default='prepare')
    p.add_argument('--original-checkpoint',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--prompt',type=Path,required=True)
    p.add_argument('--base-url');p.add_argument('--key-file',type=Path);p.add_argument('--checkpoint',type=Path,default=ROOT/'.runtime/pilot-continuation-checkpoint.json')
    p.add_argument('--output',type=Path,default=ROOT/'docs/benchmarks-next/answer-continuation-results.json');p.add_argument('--union-output',type=Path,default=ROOT/'docs/benchmarks-next/answer-pilot-union.json')
    p.add_argument('--allow-dirty',action='store_true');args=p.parse_args()
    inputs={path:path.read_bytes() for path in (args.original_checkpoint,args.manifest,args.prompt)}
    raw=inputs[args.manifest];raw=gzip.decompress(raw) if args.manifest.suffix=='.gz' else raw
    plan=build_plan(inputs[args.original_checkpoint],raw,inputs[args.prompt])
    if args.mode=='prepare':
        print(json.dumps(dict(status='prepared_no_dispatch',original_attempted=647,remaining=103,whole_plan_reservation={'input':WHOLE_INPUT,'output':WHOLE_OUTPUT},
            continuation_estimate=plan['continuation_estimate'],original_checkpoint_sha256=plan['original_checkpoint_sha256']),indent=2));return
    if not args.base_url or not args.key_file:p.error('Run requires the original provider base URL and runtime key file.')
    outputs=[args.checkpoint,args.output,args.union_output];all_paths=[p.resolve() for p in inputs]+[p.resolve() for p in outputs]
    require(len(all_paths)==len(set(all_paths)),'Inputs and outputs must be distinct paths.')
    require(not any(p.exists() for p in outputs),'Refuse to overwrite prior continuation artifacts.')
    run=BenchmarkRun(allow_dirty=args.allow_dirty);harness.check_input_bytes(inputs)
    state=dispatch(plan,base_url=args.base_url,key=args.key_file.read_text().strip(),checkpoint=args.checkpoint)
    harness.check_input_bytes(inputs);continuation,union=artifacts(plan,state)
    run.write_json(args.output,continuation);union['continuation_result_sha256']=sha(args.output.read_bytes())
    harness.check_input_bytes(inputs);run.write_json(args.union_output,union);harness.check_input_bytes(inputs)
    print(json.dumps(dict(status=union['status'],new_requests=103,total_accounted_slots=750,unknown_outcomes=1)))


if __name__=='__main__':main()
