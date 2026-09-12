from pathlib import Path
import gzip
import hashlib
import json
import pytest

ROOT=Path(__file__).resolve().parents[2]


def test_public_fantom_labels_and_published_hashes_verify():
    from benchmarks.verify_fantom import verify
    result=verify(ROOT/'docs/benchmarks-next',ROOT/'.benchmark-data')
    assert result['sets']==870 and result['methods']==5
    assert result['verified_predictions']==88820


def test_corrupt_public_gold_fails_after_updating_container_hashes(tmp_path):
    from benchmarks.verify_fantom import verify
    folder=ROOT/'docs/benchmarks-next'
    summary=json.loads((folder/'fantom-result-summary.json').read_text())
    raw=json.loads(gzip.decompress((folder/'fantom-results.json.gz').read_bytes()))
    row=next(iter(raw['methods']['Delivery projection']['per_query'].values()))
    row['gold_answer']=['Invented Label']
    original=json.dumps(raw).encode();encoded=gzip.compress(original,mtime=0)
    (tmp_path/'fantom-results.json.gz').write_bytes(encoded)
    summary['raw_artifact'].update(uncompressed_sha256=hashlib.sha256(original).hexdigest(),compressed_sha256=hashlib.sha256(encoded).hexdigest(),uncompressed_bytes=len(original),compressed_bytes=len(encoded))
    (tmp_path/'fantom-result-summary.json').write_text(json.dumps(summary))
    with pytest.raises(AssertionError,match='public gold'):
        verify(tmp_path,ROOT/'.benchmark-data')
