"""Read-only audit of amendment009f732; not an all-terminal success certificate."""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import re
from benchmarks.verify_answer_pilot import MANIFEST_SHA,PROMPT_SHA,MODEL,sha,require,number

ORIGINAL_SHA='547c173cebac53cc59e4f673b73b0fe3dedd98603e11a2c9557833cc8216c7c8'
UNCERTAIN_ID='a8879e9f8946a324aab53128227ea1928ac2232425b3e2230e6feed4cc1445cd'


def verify_union(raw,prompt,original_raw,continuation,union,*,expected_manifest_sha256=MANIFEST_SHA,
                 expected_prompt_sha256=PROMPT_SHA,expected_original_sha256=ORIGINAL_SHA,
                 query_count=50,original_count=647,uncertain_id=UNCERTAIN_ID):
    require(sha(raw)==expected_manifest_sha256 and sha(prompt)==expected_prompt_sha256,'Frozen input identity mismatch.')
    require(sha(original_raw)==expected_original_sha256,'Original checkpoint raw-byte mismatch.')
    original=json.loads(original_raw);rows=[json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    by={(r['query_id'],r['arm']):r for r in rows};queries={r['query_id'] for r in rows}
    require(len(rows)==len(by)==query_count*5 and len(queries)==query_count,'Manifest shape mismatch.')
    require(set(by)=={(q,a) for q in queries for a in 'ABCDE'},'Manifest arms mismatch.')
    expected={};reservations={}
    for repeat in range(3):
        for qid in sorted(queries):
            for arm in 'ABCDE':
                row=by[qid,arm];require(row.get('prompt_sha256')==expected_prompt_sha256,'Row prompt mismatch.')
                fields={k:row[k] for k in ('question','recipient_id','valid_at','known_at','received_by')}
                fields['context']='\n'.join(json.dumps({'id':x['id'],'text':x['text']},ensure_ascii=False) for x in row['context'])
                text=prompt.decode().format(**fields);bound=len(text.encode())+512
                require(bound<=(16384 if arm=='B' else 8192),'Input cap violation.')
                body={'model':MODEL,'messages':[{'role':'user','content':text}],'temperature':0,'reasoning_effort':'low','max_completion_tokens':1024}
                rid=sha(json.dumps(dict(query_id=qid,arm=arm,repeat=repeat,body=body),sort_keys=True,ensure_ascii=False).encode())
                expected[rid]=(qid,arm,repeat);reservations[rid]=bound
    old=original['requests'];new=continuation['requests'];all_records=union['requests'];ids=list(expected)
    require(list(old)==ids[:original_count],'Original checkpoint is not exact planned prefix.')
    require(list(new)==ids[original_count:],'Continuation is not exact disjoint remaining suffix.')
    require(list(all_records)==ids,'Union is not all750 original ordered slots.')
    require(all_records=={**old,**new},'Union mutated original/continuation records.')
    require(union.get('status')=='completed_plan_with_uncertainty','Union mislabels uncertain completion.')
    require(continuation.get('status')=='complete','Continuation is incomplete.')
    require(original.get('actual_response_model')==MODEL,'Original returned model mismatch.')
    full_estimate=dict(queries=query_count,requests=query_count*15,repeats=3,model=MODEL,prompt_sha256=expected_prompt_sha256,
        input_token_reservation=sum(reservations.values()),output_token_reservation=len(ids)*1024,
        max_input_tokens_A_C_D_E=8192,max_input_tokens_B=16384,max_completion_tokens=1024)
    subset_estimate={**original['estimate'],'requests':len(new),'input_token_reservation':sum(reservations[rid] for rid in new),'output_token_reservation':len(new)*1024}
    for artifact in (continuation,union):
        require(artifact.get('manifest_sha256')==expected_manifest_sha256 and artifact.get('prompt_sha256')==expected_prompt_sha256,'Artifact input binding mismatch.')
        require(artifact.get('original_checkpoint_sha256')==expected_original_sha256,'Artifact original binding mismatch.')
        require(artifact.get('actual_response_model')==artifact.get('expected_response_model')==MODEL,'Artifact model mismatch.')
        require(artifact.get('estimate')==original['estimate'],'Original estimate changed.')
        require(artifact.get('continuation_estimate')==subset_estimate,'Continuation subset reservation mismatch.')
    require(all(original['estimate'].get(k)==v for k,v in full_estimate.items()),'Frozen whole-plan reservation mismatch.')
    require(uncertain_id in old and list(old)[-1]==uncertain_id,'Specified timeout is not original final slot.')
    uncertainty=old[uncertain_id]
    require(uncertainty.get('status')=='uncertain' and uncertainty.get('error_type')=='TimeoutError','Original timeout identity mismatch.')
    require(not any(k in uncertainty for k in ('usage','raw_answer','returned_model','finish_reason','scoring')),'Timeout contains fabricated response/usage.')
    if expected_original_sha256==ORIGINAL_SHA:
        require(expected[uncertain_id]==('test-0316','B',2),'Pinned timeout slot mismatch.')
        require(reservations[uncertain_id]==15241,'Pinned timeout reservation mismatch.')
    counts=Counter();arms={a:Counter() for a in 'ABCDE'};usage=Counter()
    for rid,r in all_records.items():
        qid,arm,repeat=expected[rid];bound=reservations[rid]
        require((r.get('query_id'),r.get('arm'),r.get('repeat'))==(qid,arm,repeat) and r.get('id')==rid,'Request slot mismatch.')
        require(r.get('input_reservation')==bound and r.get('output_reservation')==1024,'Request reservation mismatch.')
        require(number(r.get('seconds')),'Invalid latency.')
        require(not any(r.get(k) for k in ('budget_breach','model_guard_failure','usage_guard_failure')),'Guarded record.')
        status=r.get('status');counts[status]+=1;arms[arm][status]+=1
        if rid==uncertain_id:continue
        require(status in ('complete','truncated_or_invalid'),'Additional nonterminal/uncertain outcome.')
        require(r.get('returned_model')==MODEL,'Returned model mismatch.')
        require((status=='complete')==(r.get('finish_reason')=='stop'),'Status/finish mismatch.')
        require(isinstance(r.get('raw_answer'),str),'Missing raw answer.')
        u=r.get('usage');require(isinstance(u,dict) and all(number(u.get(k)) for k in ('prompt_tokens','completion_tokens','total_tokens')),'Missing/nonnumeric terminal usage.')
        require(u['prompt_tokens']<=bound and u['completion_tokens']<=1024 and u['total_tokens']<=bound+1024,'Usage exceeds reserved bounds.')
        for key in ('prompt_tokens','completion_tokens','total_tokens'):usage[key]+=u[key];arms[arm][key]+=u[key]
        if r.get('finish_reason')=='length':arms[arm]['length_finish_count']+=1
        if status!='complete':continue
        stripped=r['raw_answer'].strip();abstained=stripped=='INSUFFICIENT EVIDENCE'
        arms[arm]['empty_stop_completions']+=not stripped
        arms[arm]['nonabstained_completions']+=not abstained
        arms[arm]['nonempty_nonabstained_completions']+=bool(stripped) and not abstained
        if abstained:continue
        match=re.search(r'(?m)^\s*(?:CITATIONS:\s*)?(\[[^\n]*\])\s*$',stripped)
        try:
            citations=json.loads(match[1]) if match else None
            parsed=isinstance(citations,list) and all(isinstance(x,str) for x in citations)
        except (ValueError,TypeError):parsed=False
        arms[arm]['citation_parse_error']+=not parsed
    require(counts['uncertain']==1,'Uncertainty count mismatch.')
    return dict(status='completed_plan_with_uncertainty',audit_passed=True,queries=query_count,planned_slots=len(ids),
        original_slots=len(old),continuation_slots=len(new),terminal_responses=len(ids)-1,uncertain_outcomes=1,
        unknown_usage_slots=1,unknown_usage_reserved_input_tokens=reservations[uncertain_id],unknown_usage_reserved_output_tokens=1024,
        original_checkpoint_sha256=sha(original_raw),manifest_sha256=sha(raw),prompt_sha256=sha(prompt),model=MODEL,
        statuses=dict(counts),observed_tokens=dict(usage),arms={a:dict(c) for a,c in arms.items()},
        continuation_arm_counts=dict(Counter(r['arm'] for r in new.values())),
        continuation_repeat_counts=dict(Counter(r['repeat'] for r in new.values())),
        continuation_query_count=len({r['query_id'] for r in new.values()}),
        limitations=['All planned slots accounted for; not750 successful or terminal responses.','Timeout charge and usage are unknown, not zero.',
        'Transport interruption and separate phases prevent a controlled latency comparison; provider/backend drift remains possible despite unchanged returned model identity.','Citation diagnostics use the frozen permissive parser, not strict format compliance.',
        'Nonempty/nonabstained does not establish a substantive answer; no semantic correctness or uncited leakage adjudication.'])


def verify_bindings(raw):
    continuation=json.loads(raw['continuation']);union=json.loads(raw['union'])
    require(union.get('continuation_result_sha256')==sha(raw['continuation']),'Continuation file binding mismatch.')
    original=json.loads(raw['original'])
    canonical=sha(json.dumps(original['requests'],sort_keys=True,ensure_ascii=False).encode())
    require(continuation.get('phase')=='undispatched_only_continuation','Incorrect continuation phase.')
    require(union.get('phase')=='original_plus_undispatched_continuation','Incorrect union phase.')
    for artifact in (continuation,union):
        require(artifact.get('original_records_json_sha256')==canonical,'Original record digest mismatch.')
        require(artifact.get('original_source_commit')=='9ece9b9','Original source attribution mismatch.')
        require(artifact.get('repaired_execute_commit')=='e77c0d7' and artifact.get('amendment_commit')=='009f732','Repair/amendment attribution mismatch.')
        require(artifact.get('unknown_original_request_id')==UNCERTAIN_ID and artifact.get('unknown_original_usage') is True,'Unknown original outcome is not explicitly retained.')
        require(artifact.get('original_run_id')==original.get('run_id') and bool(original.get('run_id')),'Original run identity mismatch.')
        require(bool(artifact.get('continuation_run_id')),'Missing continuation run identity.')
        provenance=artifact.get('provenance',{})
        require(bool(provenance.get('git_commit')) and isinstance(provenance.get('source_sha256'),dict),'Missing continuation source provenance.')
    require(union['continuation_run_id']==continuation['continuation_run_id'],'Continuation run identity mismatch.')
    require(union['provenance']['git_commit']==continuation['provenance']['git_commit'],'Continuation source commits differ.')
    require(union['provenance']['source_sha256']==continuation['provenance']['source_sha256'],'Continuation source digests differ.')
    return continuation,union


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','prompt','original','continuation','union'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    paths={name:getattr(args,name) for name in ('manifest','prompt','original','continuation','union')}
    stored={k:p.read_bytes() for k,p in paths.items()};raw={k:gzip.decompress(v) if paths[k].suffix=='.gz' else v for k,v in stored.items()}
    continuation,union=verify_bindings(raw)
    audit=verify_union(raw['manifest'],raw['prompt'],raw['original'],continuation,union)
    audit.update(file_sha256={k:sha(v) for k,v in stored.items()},raw_sha256={k:sha(v) for k,v in raw.items()},
        verifier_sha256=sha(Path(__file__).read_bytes()),original_source_commit='9ece9b9',continuation_source_commit=continuation['provenance']['git_commit'])
    require(all(p.read_bytes()==stored[k] for k,p in paths.items()),'Audit input changed.')
    output=json.dumps(audit,indent=2)+'\n'
    if args.output:
        require(not args.output.exists() and args.output.resolve() not in {p.resolve() for p in paths.values()},'Refuse existing/input output path.')
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(output)
    print(output)


if __name__=='__main__':main()
