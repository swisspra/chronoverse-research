"""Offline packaging/reuse invariants; no model/provider inference in tests."""
import gzip
import hashlib
import json
from pathlib import Path
import pytest
from benchmarks.answer_full500 import ChunkWriter,estimates,frozen_pilot,reuse_pilot


class Writer:
    def write_bytes(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        return {'provenance':{'synthetic_test':True}}


def test_chunked_bytes_roundtrip_exact_sha_and_deterministic_gzip(tmp_path):
    lines=[(json.dumps({'index':i,'text':'ทดสอบ '+str(i)*10},ensure_ascii=False,sort_keys=True)+'\n').encode() for i in range(40)]
    def write(folder):
        writer=ChunkWriter(Writer(),folder,max_raw_bytes=256)
        for line in lines:writer.append(line)
        return writer.finish()
    first=write(tmp_path/'one');second=write(tmp_path/'two');raw=b''.join(lines)
    assert first['manifest_sha256']==hashlib.sha256(raw).hexdigest() and first['row_count']==40
    recovered=b''
    for a,b in zip(first['chunks'],second['chunks'],strict=True):
        one=(tmp_path/'one'/a['file']).read_bytes();two=(tmp_path/'two'/b['file']).read_bytes()
        assert one==two and one[4:8]==b'\0\0\0\0'
        part=gzip.decompress(one);assert hashlib.sha256(part).hexdigest()==a['raw_sha256'];recovered+=part
        assert a['raw_bytes']<=256 and a['compressed_bytes']<90*1024**2
    assert recovered==raw and len(first['chunks'])>1
    with pytest.raises(ValueError,match='single JSONL'):ChunkWriter(Writer(),tmp_path/'bad',3).append(b'four')


def test_reuse_preserves_pilot_and_only_sends_new_public_queries_to_local_models():
    queries=[{'id':id,'query':'Question '+id,'recipient_id':'R','scope':{},'gold_assertion_ids':['SECRET']} for id in ('old','new')]
    prior={'selected_query_ids':['old'],'trace':{'old':{'dense_top50':['old-dense'],'cross_encoder_top50':['old-ce']}}};called=[]
    def rank(units,public):
        called.extend(public);return {'new':['new-dense']},{'new':['new-ce']}
    pools,ce,remaining=reuse_pilot(queries,prior,[],rank)
    assert pools=={'old':['old-dense'],'new':['new-dense']} and ce['old']==['old-ce']
    assert [q['id'] for q in remaining]==['new'] and [q['id'] for q in called]==['new']
    assert 'gold_assertion_ids' not in called[0]
    with pytest.raises(ValueError,match='coverage'):reuse_pilot(queries,prior,[],lambda *args:({},{}))


def test_frozen_pilot_hash_and_complete_arm_coverage(tmp_path):
    ids=[str(i) for i in range(50)];raw=b''.join((json.dumps({'query_id':id,'arm':a})+'\n').encode() for id in ids for a in 'ABCDE')
    prior={'selected_query_ids':ids,'manifest_sha256':hashlib.sha256(raw).hexdigest()};path=tmp_path/'pilot.jsonl.gz';path.write_bytes(gzip.compress(raw,mtime=0))
    assert len(frozen_pilot(path,prior))==250
    path.write_bytes(gzip.compress(raw+b'\n',mtime=0))
    with pytest.raises((ValueError,json.JSONDecodeError)):frozen_pilot(path,prior)


def test_future4096_is_separate_option_and_input_overruns_are_exposed():
    bounds={arm:[9000 if arm=='A' else 4000]*500 for arm in 'ABCDE'};value=estimates(bounds,500)
    assert value['requests']==7500 and value['rows_exceeding_frozen_input_caps']['A']==500
    assert value['completion_options'][0]['output_token_reservation']==7680000
    assert value['completion_options'][1]['output_token_reservation']==30720000
    assert value['usd'] is None
