"""Synthetic-only tests; no hosted answers or frozen TEST outputs are read."""
from copy import deepcopy

import pytest

from benchmarks.clock_answer_statistics import ARMS, COMPARATORS, summarize


def manifest_rows(query_count: int = 4):
    rows = []
    for index in range(query_count):
        answerable = index % 2 == 0
        for arm in ARMS:
            rows.append(
                {
                    'query_id': f'q-{index}',
                    'arm': arm,
                    'question': 'What is the value?',
                    'recipient_id': 'recipient',
                    'valid_at': '2026-01-01T00:00:00Z',
                    'known_at': '2026-01-02T00:00:00Z',
                    'received_by': '2026-01-02T00:00:00Z',
                    'expected_answers': ['2'] if answerable else [],
                    'gold_support_ids': ['assertion:x'] if answerable else [],
                    'support_equivalence_groups': (
                        [{'required_id': 'assertion:x', 'acceptable_ids': ['assertion:x']}]
                        if answerable
                        else []
                    ),
                    'visible_ids': ['assertion:x'],
                    'stale_ids': [],
                    'answerable': answerable,
                    'family': f'family-{index}',
                    'event_only': False,
                    'context': [{'id': 'assertion:x', 'text': 'The value is 2.'}],
                }
            )
    return rows


def completed_records(rows):
    records = {}
    for row in rows:
        for repeat in range(3):
            key = f"{row['query_id']}/{row['arm']}/{repeat}"
            records[key] = {
                'query_id': row['query_id'],
                'arm': row['arm'],
                'repeat': repeat,
                'status': 'complete',
                'finish_reason': 'stop',
                'returned_model': 'fixed',
                'raw_answer': (
                    '2\n["assertion:x"]'
                    if row['answerable']
                    else 'INSUFFICIENT EVIDENCE'
                ),
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
                'seconds': 1.0,
            }
    return records


def test_only_three_preregistered_full_minus_other_contrasts():
    rows = manifest_rows()
    result = summarize(rows, completed_records(rows), 'fixed', expected_queries=4, samples=100)
    assert result['planned_requests'] == 48
    for metric, family in result['paired_contrasts'].items():
        assert tuple(family['comparisons']) == tuple(f'FULL-{arm}' for arm in COMPARATORS)
        assert family['family_size'] == 3
        assert family['simultaneous_intervals'].startswith('Bonferroni')
        assert 'distinct from Holm-adjusted p-values' in family['simultaneous_intervals']
        assert 'not jointly controlled' in family['cross_metric_multiplicity']
        for comparison in family['comparisons'].values():
            if 'p_value' in comparison:
                assert comparison['family_size'] == 3
                assert comparison['independent_units'] == comparison['query_pairs']
                assert comparison['simultaneous_ci'][0] <= comparison['raw_ci95'][0]
                assert comparison['simultaneous_ci'][1] >= comparison['raw_ci95'][1]


def test_missing_and_truncated_fail_outcomes_but_leave_behavior_audits_unknown():
    rows = manifest_rows(2)
    records = completed_records(rows)
    del records['q-0/FULL/2']
    records['q-0/VK/1'].update(status='truncated_or_invalid', finish_reason='length')
    result = summarize(rows, records, 'fixed', expected_queries=2, samples=100)

    full = result['arms']['FULL']['metrics']
    vk = result['arms']['VK']['metrics']
    assert full['closed_form'] == {'value': pytest.approx(5 / 6), 'denominator': 6}
    assert vk['closed_form'] == {'value': pytest.approx(5 / 6), 'denominator': 6}
    assert full['support_recovery'] == {'value': pytest.approx(2 / 3), 'denominator': 3}
    assert vk['support_recovery'] == {'value': pytest.approx(2 / 3), 'denominator': 3}
    assert full['strict_support_complete'] == {
        'value': pytest.approx(2 / 3),
        'denominator': 3,
    }
    assert full['false_abstention']['denominator'] == 2
    assert vk['false_abstention']['denominator'] == 2
    assert result['arms']['FULL']['statuses']['missing'] == 1
    assert result['arms']['VK']['statuses']['truncated_or_invalid'] == 1

    # Failure-as-zero retains both planned queries for answer accuracy.
    accuracy = result['paired_contrasts']['closed_form']['comparisons']['FULL-VK']
    assert accuracy['query_pairs'] == 2
    # Answer behavior is unknowable for the failed answerable slots.
    false_abstention = result['paired_contrasts']['false_abstention']['comparisons']['FULL-VK']
    assert false_abstention['query_pairs'] == 0
    assert false_abstention['excluded_query_count'] == 1
    assert 'p_value' not in false_abstention
    assert result['missing_and_truncation_policy']['attempt_costs'].startswith('all recorded')


def test_wrong_model_is_an_outcome_failure_and_attempt_cost_remains_visible():
    rows = manifest_rows(2)
    records = completed_records(rows)
    records['q-0/FULL/0']['returned_model'] = 'substituted'
    result = summarize(rows, records, 'fixed', expected_queries=2, samples=100)
    assert result['arms']['FULL']['metrics']['closed_form']['value'] == pytest.approx(5 / 6)
    assert result['arms']['FULL']['resources']['recorded_attempts'] == 6
    assert result['arms']['FULL']['resources']['valid_completed_attempts'] == 5
    assert result['actual_response_models']['substituted'] == 1


def test_manifest_requires_exact_arms_shared_labels_and_unique_dispatch_slots():
    rows = manifest_rows(2)
    records = completed_records(rows)
    with pytest.raises(ValueError, match='FULL, VK, V, and NONE'):
        summarize(rows[:-1], records, 'fixed', expected_queries=2, samples=100)

    changed = deepcopy(rows)
    changed[1]['gold_support_ids'] = ['other']
    with pytest.raises(ValueError, match='metadata differs'):
        summarize(changed, records, 'fixed', expected_queries=2, samples=100)

    duplicate = deepcopy(records['q-0/FULL/0'])
    records['duplicate'] = duplicate
    with pytest.raises(ValueError, match='duplicate'):
        summarize(rows, records, 'fixed', expected_queries=2, samples=100)


def test_expected_frozen_query_count_is_enforced():
    rows = manifest_rows(2)
    with pytest.raises(ValueError, match='exactly 50'):
        summarize(rows, completed_records(rows), 'fixed', samples=100)
