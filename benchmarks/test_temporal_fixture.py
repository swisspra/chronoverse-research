"""Independent review of immutable, manually authored temporal-v1 relevance judgments.

This module never rewrites fixture gold, imports the benchmark runner, or uses Store
outputs to create expected answers. The declarative expected objects below come
from the scenario descriptions. Store is checked only after those assertions hold.
"""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

FIXTURE = json.loads((Path(__file__).parent / 'data' / 'temporal-v1.json').read_text())
ASSERTIONS = {row['id']: row for row in FIXTURE['assertions']}

# Independent, fixed semantic expectations for each of the 21 scenario templates.
EXPECTED_OBJECTS = {
    'valid_before_change': {'Mira Holt'},
    'valid_after_change': {'Theo Reed'},
    'exclusive_boundary': {'Theo Reed'},
    'known_before_change': {'Mira Holt'},
    'late_correction_before': {'12'},
    'late_correction_after': {'2'},
    'retraction_before': {'collapsed'},
    'retraction_empty': set(),
    'plane_fact': {'spherical'},
    'plane_belief': {'flat'},
    'world_main': {'Northport'},
    'world_counterfactual': {'Southport'},
    'perspective_municipal': {'June 11'},
    'perspective_press': {'June 12'},
    'preserve_conflict': {'June 5', 'June 6'},
    'future_knowledge_empty': set(),
    'future_knowledge_visible': {'successful'},
    'finite_interval_inside': {'authorized'},
    'finite_interval_empty': set(),
    'theory_domain_classical': {'Newtonian approximation'},
    'theory_domain_relativistic': {'general relativity'},
}


def utc(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def reference_eligible(row, scope):
    """Small public-spec oracle for this fixture's single-event lifecycles only.

    No token matching, scores, Store helpers, or relevance judgments participate.
    Retiring events here all take effect at their target's June 1 start (except
    supersession); do not present this as a validated general lifecycle engine.
    """
    valid, known = utc(scope['valid_at']), utc(scope['known_at'])
    if utc(row['recorded_at']) > known or utc(row['valid_from']) > valid:
        return False
    if row.get('valid_to') and valid >= utc(row['valid_to']):
        return False
    for key in ('world', 'plane', 'perspective'):
        if scope[key] != 'all' and row[key] != scope[key]:
            return False
    for event in FIXTURE['events']:
        if (event['assertion_id'] == row['id']
                and utc(event['recorded_at']) <= known
                and utc(event['effective_at']) <= valid):
            return False
    return True


def test_inventory_has_21_templates_not_252_independent_scenarios():
    assert len(ASSERTIONS) == len(FIXTURE['assertions']) == 204
    assert len(FIXTURE['events']) == 36
    assert len({event['id'] for event in FIXTURE['events']}) == 36
    assert len({query['id'] for query in FIXTURE['queries']}) == 252
    assert Counter(query['category'] for query in FIXTURE['queries']) == Counter({name: 12 for name in EXPECTED_OBJECTS})
    assert Counter(len(query['gold_assertion_ids']) for query in FIXTURE['queries']) == {0: 36, 1: 204, 2: 12}
    assert FIXTURE['synthetic'] is True


def test_gold_matches_independent_semantic_expectations_and_subjects():
    for query in FIXTURE['queries']:
        gold = query['gold_assertion_ids']
        assert len(gold) == len(set(gold)), query['id']
        assert set(gold) <= ASSERTIONS.keys(), query['id']
        assert {ASSERTIONS[aid]['object'] for aid in gold} == EXPECTED_OBJECTS[query['category']], query['id']
        for aid in gold:
            row = ASSERTIONS[aid]
            assert f"{row['subject']} {row['predicate']}" == query['query'], query['id']


def test_manual_gold_exactly_covers_the_query_relationship_in_reference_scope():
    for query in FIXTURE['queries']:
        eligible_target_ids = {
            row['id'] for row in ASSERTIONS.values()
            if f"{row['subject']} {row['predicate']}" == query['query']
            and reference_eligible(row, query['scope'])
        }
        assert eligible_target_ids == set(query['gold_assertion_ids']), query['id']


def test_boundary_and_conflict_cases_cannot_be_explained_away_by_single_hit():
    for query in FIXTURE['queries']:
        category, scope = query['category'], query['scope']
        if category == 'exclusive_boundary':
            assert utc(scope['valid_at']) == utc('2023-06-01')
            assert EXPECTED_OBJECTS[category] == {'Theo Reed'}
        elif category == 'finite_interval_empty':
            assert utc(scope['valid_at']) == utc('2023-06-01')
            assert query['gold_assertion_ids'] == []
        elif category == 'future_knowledge_visible':
            aid, = query['gold_assertion_ids']
            assert utc(ASSERTIONS[aid]['recorded_at']) == utc(scope['known_at'])
        elif category == 'preserve_conflict':
            assert len(query['gold_assertion_ids']) == 2
            assert {ASSERTIONS[aid]['object'] for aid in query['gold_assertion_ids']} == {'June 5', 'June 6'}


@pytest.fixture(scope='module')
def store():
    from chronoverse.models import AssertionInput, EventInput
    from chronoverse.store import Store
    ledger = Store(':memory:', seed=False)
    try:
        for row in FIXTURE['assertions']:
            ledger.add_assertion(AssertionInput(**row))
        for row in FIXTURE['events']:
            payload = dict(row)
            target = payload.pop('assertion_id')
            ledger.add_event(target, EventInput(**payload))
        yield ledger
    finally:
        ledger.close()


@pytest.mark.parametrize('query', FIXTURE['queries'], ids=lambda query: f"{query['id']}-{query['category']}")
def test_store_scope_eligibility_against_independent_fixture_oracle(store, query):
    from chronoverse.models import QueryRequest
    expected = {row['id'] for row in ASSERTIONS.values() if reference_eligible(row, query['scope'])}
    # Empty text returns all eligible rows: this tests coordinates, not ranking.
    assert len(expected) <= 100, 'API limit would silently truncate the eligibility check'
    actual = store.query(QueryRequest(query='', limit=100, **query['scope']))
    assert {row['id'] for row in actual['results']} == expected
    assert set(query['gold_assertion_ids']) <= expected
