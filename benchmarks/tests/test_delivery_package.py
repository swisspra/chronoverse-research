import gzip
import hashlib
import json


def test_packaging_preserves_exact_raw_bytes_and_retains_original_provenance(tmp_path):
    from benchmarks.delivery_package import package
    class Writer:
        def write_bytes(self,path,content):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            return {'sha256':hashlib.sha256(content).hexdigest(),'provenance':{'git_commit':'package'}}
        def write_json(self,path,value):
            path.write_text(json.dumps(value));return value
    raw=b'{"status":"complete", "methods":{"method":{"metrics":{"value":0.5},"per_query":{"q":{}}}}, "query_manifest":[{"split":"test"}], "provenance":{"git_commit":"measurement"}}\n'
    result=tmp_path/'original.json';result.write_bytes(raw)
    contexts=tmp_path/'contexts.json';contexts.write_bytes(b'{"arms":{}}\n')
    value=package(Writer(),result,contexts,tmp_path/'out')
    assert gzip.decompress((tmp_path/'out'/'results.json.gz').read_bytes())==raw
    assert result.read_bytes()==raw
    assert value['original_result_provenance']['git_commit']=='measurement'
    assert value['methods']['method']['metrics']['value']==.5
    assert 'per_query' not in value['methods']['method']
    assert value['split_counts']=={'test':1}
    assert value['raw_artifacts']['results.json']['uncompressed_sha256']==hashlib.sha256(raw).hexdigest()
