"""Run the gold cases authored by a fresh, specification-only API conversation."""
import json
from pathlib import Path
import pytest
from benchmarks.reference_v3 import project

CASES=json.loads((Path(__file__).resolve().parents[1]/'data/reference-v3-cases.json').read_text())

@pytest.mark.parametrize('case',CASES,ids=lambda case:case['name'])
def test_reference_author_gold(case):
    actual=project(case['ledger'],case['query'])
    assert sorted(r['id'] for r in actual['assertions'])==sorted(case['expected_assertion_ids'])
    assert sorted(r['id'] for r in actual['evidence'])==sorted(case['expected_evidence_ids'])
    assert sorted(r['id'] for r in actual['events'])==sorted(case['expected_event_ids'])
