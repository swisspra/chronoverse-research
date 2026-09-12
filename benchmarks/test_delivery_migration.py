"""Historical-result preservation and read-only delivery verification."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from benchmarks.delivery_fixture import generate
from benchmarks.verify_delivery_experiment import OUT, ROOT, verify


def test_schema_migration_preserves_ranked_inputs_and_gold():
    old=json.loads((ROOT/'docs/benchmarks-observer/fixture.json').read_text())
    new=generate()
    assert new==json.loads((ROOT/'benchmarks/data/delivery-v1.json').read_text())
    assert old['assertions']==new['assertions'] and old['events']==new['events']
    for before,after in zip(old['queries'],new['queries'],strict=True):
        assert before['query']==after['query']
        for key in ('gold_assertion_ids','gold_evidence_ids','gold_event_ids'):
            assert before[key]==after[key]
        assert before['scope']['observer_at']==after['scope']['received_by']
    orphan=next(q for q in new['queries'] if q['id']=='oq41')
    assert not orphan['gold_assertion_ids'] and orphan['gold_evidence_ids']==['tu6h-e1']


def copied_artifacts(target):
    for name in ('results.json','fixture.json','migration-manifest.json'):
        shutil.copy2(OUT/name,target/name)


def test_verification_is_read_only_on_copied_artifacts(tmp_path):
    copied_artifacts(tmp_path)
    before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    assert verify(tmp_path)['status']=='passed'
    assert before=={p.name:p.read_bytes() for p in tmp_path.iterdir()}


def test_corrupted_metric_rejected_even_if_migration_hash_is_recomputed(tmp_path):
    copied_artifacts(tmp_path)
    path=tmp_path/'results.json'
    result=json.loads(path.read_text())
    result['methods']['Delivery projection']['metrics']['support_recall']=1.0
    path.write_text(json.dumps(result))
    manifest=json.loads((tmp_path/'migration-manifest.json').read_text())
    manifest['files']['results']['new_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path/'migration-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(AssertionError):verify(tmp_path)
