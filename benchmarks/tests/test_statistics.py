import pytest
from benchmarks.statistics import holm, paired_comparison, comparison_family


def test_holm_known_example_and_order():
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm([1, 0]) == [1, 0]


def test_identical_pairs_remain_null():
    row = paired_comparison([1, 0, 1], [1, 0, 1], samples=1000)
    assert row['mean_difference'] == 0
    assert row['p_value'] == 1
    assert row['raw_ci95'] == [0, 0]


def test_clustered_pairs_use_scenario_count():
    row = paired_comparison([1, 1, 0, 0], [0, 0, 0, 0], clusters=['a', 'a', 'b', 'b'], samples=1000)
    assert row['independent_units'] == 2
    assert row['queries'] == 4
    assert row['mean_difference'] == .5
    assert row['simultaneous_ci'][0] <= row['raw_ci95'][0]
    assert row['simultaneous_ci'][1] >= row['raw_ci95'][1]


def test_family_adjusts_all_contrasts_and_validates():
    rows = comparison_family({'a': ([1]*20, [0]*20), 'b': ([0]*20, [0]*20)}, samples=1000)
    assert rows['a']['holm_p_value'] >= rows['a']['p_value']
    assert rows['b']['holm_p_value'] == 1
    with pytest.raises(ValueError):
        paired_comparison([1], [])
    with pytest.raises(ValueError):
        paired_comparison([float('nan')], [0])
