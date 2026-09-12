"""Bounded OpenAI-compatible answer harness; dry by default, no implicit retries."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from benchmarks.provenance import BenchmarkRun

ROOT=Path(__file__).resolve().parents[1]
PROMPT=ROOT/'docs/benchmarks-next/answer-prompt-v2.txt'
ARMS=('A','B','C','D','E')


def digest(value):return hashlib.sha256(value).hexdigest()


def check_input_bytes(snapshot):
    if any(path.read_bytes()!=original for path,original in snapshot.items()):raise RuntimeError('Manifest or prompt changed during the run; captured input identity is preserved and publication refused.')


def render_prompt(row,template):
    fields={k:row[k] for k in ('question','recipient_id','valid_at','known_at','received_by')}
    fields['context']='\n'.join(json.dumps({'id':item['id'],'text':item['text']},ensure_ascii=False) for item in row['context'])
    return template.format(**fields)


def support_groups(row):
    gold=set(row['gold_support_ids'])
    groups=row.get('support_equivalence_groups',[{'required_id':id,'acceptable_ids':[id]} for id in sorted(gold)])
    if not isinstance(groups,list):raise ValueError('Support equivalence groups must be a list.')
    required=[]
    for group in groups:
        if not isinstance(group,dict) or not isinstance(group.get('required_id'),str):raise ValueError('Malformed support equivalence group.')
        alternatives=group.get('acceptable_ids')
        if not isinstance(alternatives,list) or any(not isinstance(id,str) or not id for id in alternatives) or len(alternatives)!=len(set(alternatives)):raise ValueError('Malformed acceptable support IDs.')
        required.append(group['required_id'])
    if len(required)!=len(set(required)) or set(required)!=gold:raise ValueError('Support equivalence groups must match every gold required ID exactly once.')
    return groups


def prepare(rows,template,model,*,max_input_tokens,long_max_input_tokens,max_completion_tokens,repeats=3,arms=ARMS):
    assert repeats==3,'Protocol requires three repeats.'
    arms=tuple(arms)
    if not arms or len(set(arms))!=len(arms):raise ValueError('Expected arm names must be nonempty and unique.')
    if min(max_input_tokens,long_max_input_tokens,max_completion_tokens)<=0:raise ValueError('Positive explicit token limits required.')
    prompt_hash=digest(template.encode());seen=set();groups={};requests=[]
    for row in rows:
        support_groups(row)
        key=(row['query_id'],row['arm'])
        if key in seen:raise ValueError('Duplicate query/arm manifest row.')
        seen.add(key);groups.setdefault(row['query_id'],set()).add(row['arm'])
        if row.get('prompt_sha256')!=prompt_hash:raise ValueError('Prompt hash mismatch; no dispatch.')
        if row['arm'] not in arms:raise ValueError('Unknown arm.')
        ids=[item['id'] for item in row['context']]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate context IDs.')
        text=render_prompt(row,template)
        # Conservative byte-token bound plus fixed allowance for chat framing.
        bound=len(text.encode('utf-8'))+512
        limit=long_max_input_tokens if row['arm']=='B' else max_input_tokens
        if bound>limit:raise ValueError(f"Input cap exceeded for {row['query_id']} arm {row['arm']}; no silent truncation.")
        for repeat in range(repeats):
            body={'model':model,'messages':[{'role':'user','content':text}],
                  'temperature':0,'reasoning_effort':'low','max_completion_tokens':max_completion_tokens}
            identity={'query_id':row['query_id'],'arm':row['arm'],'repeat':repeat,'body':body}
            request_id=digest(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode())
            requests.append({'id':request_id,'query_id':row['query_id'],'arm':row['arm'],'repeat':repeat,
                             'body':body,'input_reservation':bound,'output_reservation':max_completion_tokens})
    if any(found!=set(arms) for found in groups.values()):raise ValueError('Every query requires exactly the declared arms.')
    requests.sort(key=lambda r:(r['repeat'],r['query_id'],arms.index(r['arm'])))
    return requests,{'queries':len(groups),'requests':len(requests),'repeats':repeats,'prompt_sha256':prompt_hash,
        'arms':list(arms),
        'input_token_reservation':sum(r['input_reservation'] for r in requests),
        'output_token_reservation':sum(r['output_reservation'] for r in requests),
        'counting':'UTF-8 bytes + 512 chat-framing allowance; not exact model tokenizer count',
        'model':model,'transport':'Synchronous, one worker; Batch availability unverified',
        'max_input_tokens_A_C_D_E':max_input_tokens,'max_input_tokens_B':long_max_input_tokens,
        'max_completion_tokens':max_completion_tokens}


def score_answer(text,row):
    stripped=text.strip();abstained=stripped=='INSUFFICIENT EVIDENCE'
    citations=[];citation_parse_error=False
    if not abstained:
        match=re.search(r'(?m)^\s*(?:CITATIONS:\s*)?(\[[^\n]*\])\s*$',stripped)
        try:
            citations=json.loads(match[1]) if match else []
            if not isinstance(citations,list) or any(not isinstance(x,str) for x in citations):raise ValueError()
        except (ValueError,TypeError):citations=[];citation_parse_error=True
        if not match:citation_parse_error=True
    normalize=lambda value:' '.join(value.casefold().split())
    answer=stripped[:match.start()].strip() if not abstained and match else stripped
    predicted=set(citations);visible=set(row['visible_ids']);stale=set(row.get('stale_ids',[]));gold=set(row['gold_support_ids'])
    context_ids={c['id'] for c in row['context']}
    groups=support_groups(row)
    eligible_citations=(predicted&visible&context_ids)-stale
    missing_groups=[g['required_id'] for g in groups if not eligible_citations.intersection(g['acceptable_ids'])]
    answerable=row['answerable']
    required=row['expected_answers']
    closed_form=bool(required) and all(re.search(r'(?<!\w)'+re.escape(normalize(x))+r'(?!\w)',normalize(answer)) for x in required)
    return {'answer':answer,'citations':citations,'abstained':abstained,'citation_parse_error':citation_parse_error,
        'answer_closed_form_match':abstained if not answerable else bool(closed_form),
        'closed_form_rule':'Every expected string must appear with token boundaries; semantic equivalence/negation not adjudicated',
        'correct_abstention':not answerable and abstained,'false_abstention':answerable and abstained,
        'support_recall':len(predicted&gold)/len(gold) if gold else None,
        'support_complete':gold<=predicted,'missing_support_ids':sorted(gold-predicted),
        'equivalent_support_recall':(len(groups)-len(missing_groups))/len(groups) if groups else None,
        'equivalent_support_complete':not missing_groups,'missing_support_groups':missing_groups,
        'support_metric_roles':'Primary: eligible citation support equivalence groups. Supplementary: strict typed-ID support. Closed-form answer matching is separate.',
        'citation_leak_ids':sorted(predicted-visible),'stale_citation_ids':sorted(predicted&stale),
        'unknown_context_citation_ids':sorted(predicted-context_ids),'event_only':bool(row.get('event_only')),
        'content_leakage':'not adjudicated; citation checks do not establish absence of uncited semantic leakage'}


def safe_endpoint(base):
    parsed=urlsplit(base)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Base URL must be HTTP(S) without credentials/query/fragment.')
    return base.rstrip('/')+'/chat/completions'


def transport(endpoint,key,body,timeout):
    request=Request(endpoint,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    with urlopen(request,timeout=timeout) as response:return json.load(response)


def atomic_checkpoint(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w') as handle:
        json.dump(value,handle,ensure_ascii=False,indent=2);handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(path)


@contextmanager
def checkpoint_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix(path.suffix+'.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Checkpoint already in use; no concurrent dispatch.')
        yield


def execute(requests,rows,estimate,*,base_url,key,checkpoint,max_total_input_tokens,max_total_output_tokens,expected_response_model=None,timeout=90,send=transport):
    endpoint=safe_endpoint(base_url)
    if not key.strip():raise ValueError('Empty API credential; no dispatch.')
    if max_total_input_tokens<=0 or max_total_output_tokens<=0:raise ValueError('Explicit positive cumulative budgets required.')
    if estimate['input_token_reservation']>max_total_input_tokens or estimate['output_token_reservation']>max_total_output_tokens:
        raise ValueError('Whole-run conservative reservation exceeds configured token budget; zero requests dispatched.')
    by_query={(row['query_id'],row['arm']):row for row in rows}
    identity=digest(json.dumps({'requests':requests,'base_url':base_url,'scoring_metadata':rows,
                               'expected_response_model':expected_response_model,
                               'harness_sha256':digest(Path(__file__).read_bytes())},sort_keys=True,ensure_ascii=False).encode())
    with checkpoint_lock(checkpoint):
        state=json.loads(checkpoint.read_text()) if checkpoint.exists() else {'run_id':identity,'requests':{},'estimate':estimate}
        if state['run_id']!=identity:raise ValueError('Checkpoint request/prompt/context/endpoint identity mismatch.')
        if any(r['status'] in ('pending','uncertain') or r.get('budget_breach') or r.get('model_guard_failure') for r in state['requests'].values()):raise ValueError('Uncertain or guarded prior dispatch; reconcile externally before a new run. Automatic retry refused.')
        for request in requests:
            rid=request['id']
            if rid in state['requests']:continue
            result={k:v for k,v in request.items() if k!='body'}
            result['status']='pending';state['requests'][rid]=result;atomic_checkpoint(checkpoint,state)
            start=time.perf_counter()
            try:
                response=send(endpoint,key,request['body'],timeout)
                choice=response['choices'][0];text=choice['message']['content']
                if not isinstance(text,str):raise ValueError('Missing string content')
                result.update(status='complete' if choice.get('finish_reason')=='stop' else 'truncated_or_invalid',
                    raw_answer=text,finish_reason=choice.get('finish_reason'),usage=response.get('usage'),response_id=response.get('id'),
                    returned_model=response.get('model'),seconds=time.perf_counter()-start)
                if result['status']=='complete':result['scoring']=score_answer(text,by_query[(request['query_id'],request['arm'])])
            except Exception as exc:
                # No response-body or exception-string logging: a proxy may echo secrets.
                result.update(status='uncertain',error_type=type(exc).__name__,http_status=exc.code if isinstance(exc,HTTPError) else None,seconds=time.perf_counter()-start)
                atomic_checkpoint(checkpoint,state)
                raise RuntimeError('Dispatch outcome uncertain; checkpoint retained and no retry attempted.') from None
            # Until both guards finish, the durable record remains pending.
            # A crash must not make an unchecked response resumable as complete.
            actual=result.get('returned_model')
            baseline=expected_response_model or state.get('actual_response_model')
            if not isinstance(actual,str) or not actual.strip() or (baseline is not None and actual!=baseline):
                result['model_guard_failure']='unknown identity' if not actual else 'response model mismatch'
                result.pop('scoring',None);atomic_checkpoint(checkpoint,state)
                raise RuntimeError('Actual response model unknown or inconsistent; raw result retained and further dispatch stopped.')
            state['actual_response_model']=actual
            usage=result.get('usage') or {}
            if usage.get('prompt_tokens',0)>request['input_reservation'] or usage.get('completion_tokens',0)>request['output_reservation']:
                result['budget_breach']=True;atomic_checkpoint(checkpoint,state)
                raise RuntimeError('Provider usage exceeded the conservative request reservation; further dispatch stopped.')
            atomic_checkpoint(checkpoint,state)
        return state


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('prepare','estimate','run'),default='prepare')
    parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--prompt',type=Path,default=PROMPT)
    parser.add_argument('--model',required=True);parser.add_argument('--base-url');parser.add_argument('--key-file',type=Path)
    parser.add_argument('--expected-response-model',help='Pinned actual model identity from provider preflight; aliases are not identity.')
    parser.add_argument('--arms',default=','.join(ARMS),help='Frozen arm order; default A,B,C,D,E. Clock ablation uses FULL,VK,V,NONE.')
    for name in ('max-input-tokens','max-completion-tokens'):parser.add_argument('--'+name,type=int,required=True)
    parser.add_argument('--long-max-input-tokens',type=int);parser.add_argument('--max-total-input-tokens',type=int)
    parser.add_argument('--max-total-output-tokens',type=int);parser.add_argument('--allow-dirty',action='store_true')
    parser.add_argument('--checkpoint',type=Path,default=ROOT/'.runtime/answers-checkpoint.json')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/benchmarks-next/answer-results.json')
    parser.add_argument('--input-usd-per-million',type=float);parser.add_argument('--output-usd-per-million',type=float)
    args=parser.parse_args();inputs={path:path.read_bytes() for path in (args.manifest,args.prompt)}
    manifest_hash=digest(inputs[args.manifest]);prompt_hash=digest(inputs[args.prompt])
    rows=[json.loads(line) for line in inputs[args.manifest].decode().splitlines() if line.strip()]
    if any(rate is not None and rate<0 for rate in (args.input_usd_per_million,args.output_usd_per_million)):parser.error('Configured prices cannot be negative')
    requests,estimate=prepare(rows,inputs[args.prompt].decode(),args.model,max_input_tokens=args.max_input_tokens,
        long_max_input_tokens=args.long_max_input_tokens or args.max_input_tokens,max_completion_tokens=args.max_completion_tokens,arms=args.arms.split(','))
    estimate['usd_reservation']=((estimate['input_token_reservation']*args.input_usd_per_million+estimate['output_token_reservation']*args.output_usd_per_million)/1_000_000
        if args.input_usd_per_million is not None and args.output_usd_per_million is not None else None)
    estimate['pricing']='Configured rates' if estimate['usd_reservation'] is not None else 'Proxy pricing unknown; no USD estimate claimed'
    if args.mode!='run':print(json.dumps(estimate,indent=2));return
    if not args.base_url or not args.key_file or args.max_total_input_tokens is None or args.max_total_output_tokens is None:parser.error('run requires base-url, key-file and both cumulative token limits')
    run_context=BenchmarkRun(allow_dirty=args.allow_dirty)
    check_input_bytes(inputs)
    state=execute(requests,rows,estimate,base_url=args.base_url,key=args.key_file.read_text().strip(),checkpoint=args.checkpoint,
        max_total_input_tokens=args.max_total_input_tokens,max_total_output_tokens=args.max_total_output_tokens,expected_response_model=args.expected_response_model)
    check_input_bytes(inputs)
    run_context.write_json(args.output,{'status':'complete','estimate':estimate,'actual_response_model':state.get('actual_response_model'),
        'expected_response_model':args.expected_response_model,'manifest_sha256':manifest_hash,'prompt_sha256':prompt_hash,'requests':state['requests']})
    print(json.dumps({'status':'complete','requests':len(state['requests']),'output':str(args.output)}))


if __name__=='__main__':main()
