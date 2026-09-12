import copy
import pytest
from benchmarks.aggregate_answer_continuation import label_summary,check_frozen_sources,FROZEN_SOURCES


def test_metadata_wrapper_preserves_numeric_and_per_query_outputs():
    summary={'planned_queries':50,'planned_requests':750,'recorded_requests':750,'arms':{'A':{'metric':.25}},'per_query':{'q':{'value':[1,0,0]}}}
    before=copy.deepcopy(summary)
    result=label_summary(summary)
    assert summary==before
    assert all(result[k]==v for k,v in before.items())
    assert result['execution_status']=='completed_plan_with_uncertainty'
    assert result['aggregation_coverage_status']=='all_750_planned_slots_recorded'
    assert result['status']!='complete'


def test_partial_coverage_cannot_receive_full_plan_label():
    with pytest.raises(ValueError):label_summary(dict(planned_queries=50,planned_requests=750,recorded_requests=749))


def test_modified_frozen_source_is_rejected(tmp_path):
    for relative in FROZEN_SOURCES:
        path=tmp_path/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('changed source')
    with pytest.raises(ValueError):check_frozen_sources(tmp_path)
