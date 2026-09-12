"""Read-only, post-run integrity/format audit of the frozen 50-query pilot.

No scoring/statistical definitions are changed. No provider calls or retries.
"""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

MANIFEST_SHA='e807eacb8b49a965f1c53257a7903d9006f122b1cc7facc935e5798988e872ce'
PROMPT_SHA='3bb012d59e1a712665f130637fd1c38c7d406d53d0bba5751039bf530ed7b497'
MODEL='vertex_ai/gemini-3.8-flash'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def require(condition,message):
    if not condition:raise ValueError(message)


def number(value):return type(value) in (int,float) and math.isfinite(value) and value>=0


def verify(raw,prompt,result,*,expected_manifest_sha256=MANIFEST_SHA,expected_prompt_sha256=PROMPT_SHA,query_count=50):
    require(sha(raw)==expected_manifest_sha256==result.get('manifest_sha256'),'Frozen manifest identity mismatch.')
    require(sha(prompt)==expected_prompt_sha256==result.get('prompt_sha256'),'Frozen prompt identity mismatch.')
    require(result.get('status')=='complete','Not a final complete artifact.')
    require(result.get('actual_response_model')==result.get('expected_response_model')==MODEL,'Final model identity mismatch.')
    rows=[json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    by={(r['query_id'],r['arm']):r for r in rows};queries={r['query_id'] for r in rows}
    require(len(rows)==len(by)==query_count*5 and len(queries)==query_count,'Manifest shape mismatch.')
    require(set(by)=={(q,a) for q in queries for a in 'ABCDE'},'Missing/unknown manifest arm.')
    expected={};input_total=0
    for (qid,arm),row in by.items():
        require(row.get('prompt_sha256')==expected_prompt_sha256,'Manifest row prompt mismatch.')
        fields={k:row[k] for k in ('question','recipient_id','valid_at','known_at','received_by')}
        fields['context']='\n'.join(json.dumps({'id':item['id'],'text':item['text']},ensure_ascii=False) for item in row['context'])
        text=prompt.decode().format(**fields);bound=len(text.encode())+512
        require(bound<=(16384 if arm=='B' else 8192),'Input cap violation.')
        body={'model':MODEL,'messages':[{'role':'user','content':text}],'temperature':0,'reasoning_effort':'low','max_completion_tokens':1024}
        for repeat in range(3):
            identity={'query_id':qid,'arm':arm,'repeat':repeat,'body':body}
            rid=sha(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode())
            expected[rid]=(qid,arm,repeat,bound);input_total+=bound
    records=result.get('requests',{});require(set(records)==set(expected),'Missing/unexpected request identities.')
    estimate=result.get('estimate',{})
    for key,value in dict(queries=query_count,requests=query_count*15,repeats=3,model=MODEL,prompt_sha256=expected_prompt_sha256,
                          input_token_reservation=input_total,output_token_reservation=query_count*15*1024,
                          max_input_tokens_A_C_D_E=8192,max_input_tokens_B=16384,max_completion_tokens=1024).items():
        require(estimate.get(key)==value,'Frozen estimate mismatch: '+key)
    arms={a:Counter() for a in 'ABCDE'};statuses=Counter();finishes=Counter();usage=Counter();seen=set()
    for rid,record in records.items():
        qid,arm,repeat,bound=expected[rid];slot=(record.get('query_id'),record.get('arm'),record.get('repeat'))
        require(slot==(qid,arm,repeat) and slot not in seen and record.get('id')==rid,'Dispatch slot mismatch.');seen.add(slot)
        require(record.get('input_reservation')==bound and record.get('output_reservation')==1024,'Reservation mismatch.')
        require(record.get('returned_model')==MODEL,'Returned model mismatch.')
        require(not record.get('budget_breach') and not record.get('model_guard_failure'),'Guarded response.')
        status=record.get('status');finish=record.get('finish_reason')
        require(status in ('complete','truncated_or_invalid'),'Pending/uncertain/unknown response.')
        require((status=='complete')==(finish=='stop'),'Status/finish mismatch.')
        require(isinstance(record.get('raw_answer'),str),'Missing raw answer.')
        require(number(record.get('seconds')),'Missing/invalid latency.')
        u=record.get('usage');require(isinstance(u,dict),'Missing usage.')
        require(all(number(u.get(k)) for k in ('prompt_tokens','completion_tokens','total_tokens')),'Missing/nonnumeric usage.')
        require(u['prompt_tokens']<=bound and u['completion_tokens']<=1024,'Usage exceeds reservation.')
        require(u['total_tokens']<=bound+1024,'Total usage exceeds reservation.')
        for key in ('prompt_tokens','completion_tokens','total_tokens'):usage[key]+=u[key];arms[arm][key]+=u[key]
        statuses[status]+=1;finishes[str(finish)]+=1;arms[arm]['attempts']+=1;arms[arm][status]+=1
        if finish=='length':arms[arm]['length_finish_count']+=1
        if status!='complete':continue
        stripped=record['raw_answer'].strip();abstained=stripped=='INSUFFICIENT EVIDENCE'
        arms[arm]['empty_stop_completions']+=not stripped
        arms[arm]['nonabstained_completions']+=not abstained
        arms[arm]['nonempty_nonabstained_completions']+=bool(stripped) and not abstained
        if abstained:continue
        # This reproduces the frozen permissive parser for diagnostics only.
        match=re.search(r'(?m)^\s*(?:CITATIONS:\s*)?(\[[^\n]*\])\s*$',stripped)
        try:
            citations=json.loads(match[1]) if match else None
            valid=isinstance(citations,list) and all(isinstance(item,str) for item in citations)
        except (ValueError,TypeError):valid=False
        arms[arm]['citation_parse_error']+=not valid
    totals=Counter()
    for values in arms.values():totals.update(values)
    return {'status':'passed','audit_type':'Post-run integrity and descriptive transport/format audit; no scorer changes',
        'manifest_sha256':sha(raw),'prompt_sha256':sha(prompt),'model':MODEL,'queries':query_count,'manifest_rows':len(rows),
        'unique_dispatch_slots':len(seen),'statuses':dict(statuses),'finish_reasons':dict(finishes),'observed_tokens':dict(usage),
        'totals':dict(totals),'arms':{a:dict(v) for a,v in arms.items()},
        'limitations':['Nonempty does not establish a substantive answer.','Citation parse error follows the permissive frozen parser, not strict response-format compliance.',
            'No semantic correctness, negation, or uncited content leakage adjudication.','Length/invalid responses remain failures in frozen accuracy statistics.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--prompt',type=Path,required=True);parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    captured={p:p.read_bytes() for p in (args.manifest,args.prompt,args.results)}
    raw=captured[args.manifest];raw=gzip.decompress(raw) if args.manifest.suffix=='.gz' else raw
    result_raw=captured[args.results];result_raw=gzip.decompress(result_raw) if args.results.suffix=='.gz' else result_raw
    audit=verify(raw,captured[args.prompt],json.loads(result_raw))
    audit.update(result_sha256=sha(result_raw),result_file_sha256=sha(captured[args.results]),verifier_sha256=sha(Path(__file__).read_bytes()))
    require(all(p.read_bytes()==value for p,value in captured.items()),'Audit inputs changed.')
    output=json.dumps(audit,indent=2)+'\n'
    if args.output:
        require(args.output.resolve() not in {p.resolve() for p in captured},'Refuse to overwrite an input.')
        require(not args.output.exists(),'Refuse to overwrite an existing audit.')
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(output)
    print(output)


if __name__=='__main__':main()
