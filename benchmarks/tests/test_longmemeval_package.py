import gzip
import hashlib
import json


def test_exact_context_bytes_and_compact_summary_preserved(tmp_path):
    from benchmarks.longmemeval_package import package
    class Writer:
        def write_bytes(self,path,content):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            return {'sha256':hashlib.sha256(content).hexdigest(),'provenance':{'git_commit':'pack'}}
        def write_json(self,path,value):path.write_text(json.dumps(value));return value
    contexts=b'{"question_id":"one","answerer_input":{"question":"hello"}}\n'
    (tmp_path/'contexts.jsonl').write_bytes(contexts)
    result={'status':'complete','per_query':[{'id':'one'}],'methods':{'dense':{'recall':.5}},
            'contexts_artifact':{'sha256':hashlib.sha256(contexts).hexdigest()},'provenance':{'git_commit':'run'}}
    raw=(json.dumps(result)+'\n').encode();(tmp_path/'results.json').write_bytes(raw)
    summary=package(Writer(),tmp_path/'results.json',tmp_path/'contexts.jsonl',tmp_path/'out')
    assert gzip.decompress((tmp_path/'out'/'results.json.gz').read_bytes())==raw
    assert gzip.decompress((tmp_path/'out'/'contexts.jsonl.gz').read_bytes())==contexts
    assert summary['original_result_provenance']['git_commit']=='run'
    assert 'per_query' not in summary and summary['methods']==result['methods']
