import gzip
import hashlib
import json
from pathlib import Path
import shutil
import pytest

ROOT=Path(__file__).resolve().parents[2]


def test_full_v3_verification_is_read_only():
    from benchmarks.verify_delivery_v3 import verify
    folder=ROOT/'docs/benchmarks-delivery-v3'
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
    result=verify(folder,ROOT/'benchmarks/data/delivery-v3.json.gz')
    assert result['verified_method_queries']==3948
    assert result['test_queries']==500
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


def test_corrupt_support_fails_even_when_container_hashes_are_updated(tmp_path):
    from benchmarks.verify_delivery_v3 import verify
    source=ROOT/'docs/benchmarks-delivery-v3'
    for name in ['summary.json','results.json.gz','retrieval-contexts.json.gz']:
        shutil.copyfile(source/name,tmp_path/name)
    result=json.loads(gzip.decompress((tmp_path/'results.json.gz').read_bytes()))
    row=next(iter(result['methods']['Delivery projection']['per_query'].values()))
    row['found_support'].append('assertion:invented')
    raw=json.dumps(result).encode();encoded=gzip.compress(raw,mtime=0)
    (tmp_path/'results.json.gz').write_bytes(encoded)
    summary=json.loads((tmp_path/'summary.json').read_text())
    artifact=summary['raw_artifacts']['results.json']
    artifact.update(gzip_sha256=hashlib.sha256(encoded).hexdigest(),uncompressed_sha256=hashlib.sha256(raw).hexdigest(),uncompressed_bytes=len(raw),compressed_bytes=len(encoded))
    (tmp_path/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(AssertionError,match='support'):
        verify(tmp_path,ROOT/'benchmarks/data/delivery-v3.json.gz')


def test_frozen_gate_evaluation_recomputed_from_saved_scores():
    from benchmarks.verify_delivery_v3 import verify_sufficiency
    folder=ROOT/'docs/benchmarks-delivery-v3'
    result=verify_sufficiency(folder)
    assert result['verified_test_method_queries']==3000


def test_corrupted_sufficiency_metric_is_rejected(tmp_path):
    from benchmarks.verify_delivery_v3 import verify_sufficiency
    source=ROOT/'docs/benchmarks-delivery-v3'
    for name in ['results.json.gz','frozen-dev-gate.json','sufficiency-test.json']:
        shutil.copyfile(source/name,tmp_path/name)
    value=json.loads((tmp_path/'sufficiency-test.json').read_text())
    value['methods']['Delivery projection']['after']['support_recall']+=.01
    (tmp_path/'sufficiency-test.json').write_text(json.dumps(value))
    with pytest.raises(AssertionError,match='after'):
        verify_sufficiency(tmp_path)
