"""Read-only streaming audit of full500 package bytes, overlap and token bounds."""
from __future__ import annotations
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def require(condition,message):
    if not condition:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def verify(directory,pilot_path,prompt_path):
    directory=Path(directory);pilot_path=Path(pilot_path);prompt_path=Path(prompt_path)
    manifest_bytes=(directory/'manifest.json').read_bytes();manifest=json.loads(manifest_bytes);storage=manifest['storage'];template=prompt_path.read_text()
    require(manifest['query_count']==500 and manifest['row_count']==2500,'Expected complete500 questions/2500rows.')
    ids=manifest['selected_query_ids'];require(len(ids)==len(set(ids))==500,'Invalid full query inventory.')
    require(manifest['prompt_sha256']==sha(prompt_path.read_bytes()),'Frozen prompt hash differs.')
    pilot_digest=hashlib.sha256();pilot={}
    with (gzip.open(pilot_path,'rb') if pilot_path.suffix=='.gz' else pilot_path.open('rb')) as handle:
        for line in handle:
            pilot_digest.update(line);row=json.loads(line);key=(row['query_id'],row['arm']);require(key not in pilot,'Duplicate pilot row.');pilot[key]=sha(line)
    require(len(pilot)==250 and pilot_digest.hexdigest()==manifest['pilot_raw_manifest_sha256'],'Frozen pilot bytes/hash mismatch.')
    expected=[(qid,arm) for qid in ids for arm in 'ABCDE'];full_sha=hashlib.sha256();full_bytes=0;position=0;overlap=0;bounds=defaultdict(list);compressed_bytes=0
    for index,chunk in enumerate(storage['chunks'],1):
        name=chunk['file'];require(name==f'part-{index:04d}.jsonl.gz','Chunk order/name mismatch.')
        path=directory/name;encoded=path.read_bytes();compressed_bytes+=len(encoded)
        require(len(encoded)==chunk['compressed_bytes'] and sha(encoded)==chunk['compressed_sha256'],'Compressed chunk bytes/hash mismatch.')
        require(len(encoded)<90*1024**2 and encoded[4:8]==b'\0\0\0\0','Chunk cap or deterministic gzip timestamp mismatch.')
        part_sha=hashlib.sha256();part_bytes=0;part_rows=0
        with gzip.open(path,'rb') as handle:
            for line in handle:
                require(line.endswith(b'\n'),'JSONL row lacks newline.')
                row=json.loads(line);key=(row['query_id'],row['arm'])
                require(position<len(expected) and key==expected[position],'Row order/arm/query identity mismatch.');position+=1
                require(row['prompt_sha256']==manifest['prompt_sha256'],'Row prompt hash mismatch.')
                if key in pilot:require(sha(line)==pilot[key],'Frozen pilot row changed.');overlap+=1
                fields={k:row[k] for k in ('question','recipient_id','valid_at','known_at','received_by')}
                fields['context']='\n'.join(json.dumps({'id':item['id'],'text':item['text']},ensure_ascii=False) for item in row['context'])
                bounds[row['arm']].append(len(template.format(**fields).encode())+512)
                part_sha.update(line);full_sha.update(line);part_bytes+=len(line);full_bytes+=len(line);part_rows+=1
        require(part_sha.hexdigest()==chunk['raw_sha256'] and part_bytes==chunk['raw_bytes'] and part_rows==chunk['rows'],'Raw chunk hash/bytes/rows mismatch.')
        require(part_bytes<=64*1024**2,'Raw chunk exceeds64MiB.')
    require(position==storage['row_count']==2500 and full_bytes==storage['raw_bytes'],'Total row/byte count mismatch.')
    require(full_sha.hexdigest()==storage['manifest_sha256'],'Concatenated raw manifest SHA mismatch.')
    require(overlap==manifest['pilot_exact_rows_preserved']==250,'Pilot overlap incomplete.')
    estimate=manifest['estimate'];require(estimate['queries']==500 and estimate['requests']==7500 and estimate['repeats']==3,'Request inventory mismatch.')
    require(estimate['input_token_reservation']==sum(sum(values) for values in bounds.values())*3,'Input reservation mismatch.')
    for arm,values in bounds.items():
        require(len(values)==500 and max(values)==estimate['maximum_bound_by_arm'][arm],'Arm count/maximum bound mismatch.')
        expected_cap=16384 if arm=='B' else 8192;require(estimate['input_caps'][arm]==expected_cap,'Input cap changed.')
        require(sum(v>expected_cap for v in values)==estimate['rows_exceeding_frozen_input_caps'][arm],'Input-overrun count mismatch.')
    require([option['max_completion_tokens'] for option in estimate['completion_options']]==[1024,4096],'Completion options changed.')
    for option in estimate['completion_options']:require(option['output_token_reservation']==7500*option['max_completion_tokens'],'Output reservation mismatch.')
    return {'status':'verified','queries':500,'rows':2500,'pilot_rows_byte_identical':250,'chunks':len(storage['chunks']),
        'raw_bytes':full_bytes,'compressed_bytes':compressed_bytes,'raw_sha256':full_sha.hexdigest(),'manifest_file_sha256':sha(manifest_bytes),
        'input_token_reservation':estimate['input_token_reservation'],'verifier_sha256':sha(Path(__file__).read_bytes()),
        'scope':'Independent streaming byte/order/prompt/overlap/reservation audit. No rank-model rerun, provider calls or writes by default.'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    parser.add_argument('--pilot',type=Path,default=ROOT/'docs/benchmarks-next/answer-contexts-50.jsonl.gz')
    parser.add_argument('--prompt',type=Path,default=ROOT/'docs/benchmarks-next/answer-prompt-v2.txt');parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=verify(args.directory,args.pilot,args.prompt)
    if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
