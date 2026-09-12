"""Small synthetic rows, complete500-query shape, no real-model inference."""
import gzip
import hashlib
import json
import pytest
from benchmarks.answer_full500 import ChunkWriter
from benchmarks.test_answer_full500 import Writer
from benchmarks.verify_answer_full500 import verify


@pytest.fixture
def package(tmp_path):
    directory=tmp_path/'package';prompt=tmp_path/'prompt';prompt.write_text('{question}|{context}')
    prompt_hash=hashlib.sha256(prompt.read_bytes()).hexdigest();writer=ChunkWriter(Writer(),directory,65536);pilot=[];bounds={a:[] for a in 'ABCDE'}
    ids=[str(i) for i in range(500)]
    for q in ids:
        for a in 'ABCDE':
            row={'query_id':q,'arm':a,'prompt_sha256':prompt_hash,'question':'Question '+q,'recipient_id':'R',
                'valid_at':'2025-01-01','known_at':'2025-01-02','received_by':'2025-01-02','context':[{'id':'source','text':'passage'}]}
            line=(json.dumps(row,sort_keys=True,ensure_ascii=False)+'\n').encode();writer.append(line)
            if int(q)<50:pilot.append(line)
            rendered=row['question']+'|'+json.dumps({'id':'source','text':'passage'},ensure_ascii=False);bounds[a].append(len(rendered.encode())+512)
    storage=writer.finish();pilot_raw=b''.join(pilot);pilot_file=tmp_path/'pilot.gz';pilot_file.write_bytes(gzip.compress(pilot_raw,mtime=0))
    estimate={'queries':500,'requests':7500,'repeats':3,'input_token_reservation':3*sum(sum(v) for v in bounds.values()),
        'input_caps':{a:16384 if a=='B' else 8192 for a in 'ABCDE'},'maximum_bound_by_arm':{a:max(v) for a,v in bounds.items()},
        'rows_exceeding_frozen_input_caps':{a:0 for a in 'ABCDE'},'completion_options':[{'max_completion_tokens':n,'output_token_reservation':7500*n} for n in (1024,4096)]}
    manifest={'query_count':500,'row_count':2500,'selected_query_ids':ids,'prompt_sha256':prompt_hash,'pilot_raw_manifest_sha256':hashlib.sha256(pilot_raw).hexdigest(),
        'pilot_exact_rows_preserved':250,'storage':storage,'estimate':estimate};(directory/'manifest.json').write_text(json.dumps(manifest))
    return directory,pilot_file,prompt,manifest


def test_independent_streaming_verification_retains_all_pilot_bytes(package):
    directory,pilot,prompt,_=package;before={p.name:p.read_bytes() for p in directory.iterdir()}
    report=verify(directory,pilot,prompt)
    assert report['rows']==2500 and report['queries']==500 and report['pilot_rows_byte_identical']==250
    assert {p.name:p.read_bytes() for p in directory.iterdir()}==before


def test_rehashed_chunk_cannot_hide_changed_pilot_row(package):
    directory,pilot,prompt,manifest=package;chunk=manifest['storage']['chunks'][0];path=directory/chunk['file']
    lines=gzip.decompress(path.read_bytes()).splitlines(keepends=True);row=json.loads(lines[0]);row['context'][0]['text']='modified passage'
    lines[0]=(json.dumps(row,sort_keys=True,ensure_ascii=False)+'\n').encode();raw=b''.join(lines);encoded=gzip.compress(raw,mtime=0);path.write_bytes(encoded)
    chunk.update(raw_bytes=len(raw),raw_sha256=hashlib.sha256(raw).hexdigest(),compressed_bytes=len(encoded),compressed_sha256=hashlib.sha256(encoded).hexdigest())
    (directory/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='pilot row changed'):verify(directory,pilot,prompt)
