"""Independent adversarial checks for temporal and scope semantics."""

import pytest

from chronoverse.models import AssertionInput, EventInput, QueryRequest
from chronoverse.store import Store


def assertion(assertion_id: str, **overrides) -> AssertionInput:
    value = {
        "id": assertion_id,
        "subject": "Harbor",
        "predicate": "director",
        "object": "Ada",
        "world": "main",
        "plane": "fact",
        "perspective": "general",
        "valid_from": "2026-01-01",
        "recorded_at": "2026-01-01",
        "evidence": [
            {
                "title": "Synthetic bulletin",
                "text": "Synthetic evidence for the appointment",
                "synthetic": True,
            }
        ],
    }
    value.update(overrides)
    return AssertionInput(**value)


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "review.sqlite3", seed=False)
    yield value
    value.close()


def result_ids(store: Store, **overrides) -> set[str]:
    request = {
        "query": "Harbor",
        "valid_at": "2026-09-12",
        "known_at": "2026-09-12",
        "world": "all",
        "plane": "all",
        "perspective": "all",
        "limit": 100,
    }
    request.update(overrides)
    return {row["id"] for row in store.query(QueryRequest(**request))["results"]}


def test_default_recorded_at_is_stable_under_idempotent_retry(store):
    value = assertion("default-time", recorded_at=None)
    first = store.add_assertion(value)
    second = store.add_assertion(value)
    assert first["recorded_at"] == second["recorded_at"]
    assert first["evidence"][0]["recorded_at"] == first["recorded_at"]
    assert store.meta()["counts"]["assertions"] == 1

    event = EventInput(
        id="default-event-time",
        type="retract",
        effective_at="2026-02-01",
        recorded_at=None,
        reason="Synthetic withdrawal",
        source="Synthetic source",
    )
    first_event = store.add_event("default-time", event)
    second_event = store.add_event("default-time", event)
    assert first_event == second_event
    assert store.meta()["counts"]["events"] == 1


def test_future_evidence_and_event_metadata_do_not_leak(store):
    store.add_assertion(
        assertion(
            "timed-evidence",
            evidence=[
                {
                    "title": "Known evidence",
                    "url": "https://example.test/known",
                    "text": "ordinary text",
                    "recorded_at": "2026-01-01",
                    "synthetic": True,
                },
                {
                    "title": "Future secret title",
                    "url": "https://example.test/future-secret-url",
                    "text": "futuresecretneedle",
                    "recorded_at": "2026-08-01",
                    "synthetic": True,
                },
            ],
        )
    )
    store.add_event(
        "timed-evidence",
        EventInput(
            id="future-withdrawal",
            type="retract",
            effective_at="2026-01-01",
            recorded_at="2026-09-01",
            reason="Future secret reason",
            source="https://example.test/future-event",
        ),
    )

    before = store.get_assertion(
        "timed-evidence", known_at="2026-07-01", valid_at="2026-06-01"
    )
    assert [item["title"] for item in before["evidence"]] == ["Known evidence"]
    assert before["events"] == []
    assert "timed-evidence" not in result_ids(
        store,
        query="futuresecretneedle",
        known_at="2026-07-01",
        valid_at="2026-06-01",
    )


def test_graph_node_identity_preserves_world_and_perspective_scope(store):
    store.add_assertion(assertion("main-edge", object="Ada"))
    store.add_assertion(
        assertion(
            "scenario-edge",
            world="scenario-red",
            perspective="planner",
            object="Ada",
        )
    )
    result = store.query(
        QueryRequest(
            query="Harbor",
            valid_at="2026-09-12",
            known_at="2026-09-12",
            world="all",
            plane="all",
            perspective="all",
            limit=100,
        )
    )
    assert {row["id"] for row in result["results"]} == {
        "main-edge",
        "scenario-edge",
    }
    # Equal labels in different worlds/perspectives are not the same graph identity.
    assert len(result["graph"]["nodes"]) == 4
    edge_sources = {edge["source"] for edge in result["graph"]["edges"]}
    assert len(edge_sources) == 2


def test_event_status_uses_effective_order_not_arrival_order(store):
    store.add_assertion(assertion("event-order"))
    store.add_event(
        "event-order",
        EventInput(
            id="retracted-later-in-world",
            type="retract",
            effective_at="2026-06-01",
            recorded_at="2026-06-02",
            reason="Source withdrew claim",
            source="Synthetic source",
        ),
    )
    store.add_assertion(assertion("correction", object="Bea"))
    store.add_event(
        "event-order",
        EventInput(
            id="late-arriving-old-correction",
            type="correct",
            effective_at="2026-05-01",
            recorded_at="2026-06-03",
            reason="Late notice about an older correction",
            source="Synthetic correction",
            replacement_id="correction",
        ),
    )
    detail = store.get_assertion(
        "event-order", valid_at="2026-07-01", known_at="2026-07-01"
    )
    assert detail["status"] == "retracted"


def test_supersession_replacement_covers_effective_boundary(store):
    store.add_assertion(assertion("old"))
    store.add_assertion(
        assertion(
            "future-replacement",
            object="Bea",
            valid_from="2026-08-01",
            recorded_at="2026-07-01",
        )
    )
    with pytest.raises(ValueError, match="replacement.*valid|valid.*replacement"):
        store.add_event(
            "old",
            EventInput(
                type="supersede",
                effective_at="2026-07-01",
                recorded_at="2026-07-01",
                reason="Synthetic transition",
                source="Synthetic source",
                replacement_id="future-replacement",
            ),
        )


def test_one_assertion_cannot_have_competing_supersession_targets(store):
    store.add_assertion(assertion("old"))
    store.add_assertion(assertion("new-a", object="Bea", valid_from="2026-07-01"))
    store.add_assertion(assertion("new-b", object="Cy", valid_from="2026-07-01"))
    store.add_event(
        "old",
        EventInput(
            id="first-switch",
            type="supersede",
            effective_at="2026-07-01",
            recorded_at="2026-07-02",
            reason="First synthetic replacement",
            source="Synthetic source",
            replacement_id="new-a",
        ),
    )
    with pytest.raises(ValueError, match="supersed"):
        store.add_event(
            "old",
            EventInput(
                id="second-switch",
                type="supersede",
                effective_at="2026-07-01",
                recorded_at="2026-07-03",
                reason="Conflicting synthetic replacement",
                source="Synthetic source",
                replacement_id="new-b",
            ),
        )


def test_supersession_chain_cannot_form_a_cycle(store):
    store.add_assertion(assertion("a"))
    store.add_assertion(assertion("b", object="Bea", valid_from="2026-07-01"))
    store.add_event(
        "a",
        EventInput(
            id="a-to-b",
            type="supersede",
            effective_at="2026-07-01",
            recorded_at="2026-07-02",
            reason="Synthetic transition to B",
            source="Synthetic source",
            replacement_id="b",
        ),
    )
    with pytest.raises(ValueError, match="cycle|supersed"):
        store.add_event(
            "b",
            EventInput(
                id="b-to-a",
                type="supersede",
                effective_at="2026-08-01",
                recorded_at="2026-08-02",
                reason="Invalid transition back to A",
                source="Synthetic source",
                replacement_id="a",
            ),
        )


def test_supersession_cannot_select_already_retired_replacement(store):
    store.add_assertion(assertion("old"))
    store.add_assertion(assertion("retired-new", object="Bea", valid_from="2026-07-01"))
    store.add_event(
        "retired-new",
        EventInput(
            id="withdraw-new",
            type="retract",
            effective_at="2026-07-01",
            recorded_at="2026-07-01",
            reason="Replacement withdrawn",
            source="Synthetic source",
        ),
    )
    with pytest.raises(ValueError, match="replacement.*active|active.*replacement|retir|retract"):
        store.add_event(
            "old",
            EventInput(
                id="old-to-retired",
                type="supersede",
                effective_at="2026-07-01",
                recorded_at="2026-07-02",
                reason="Invalid transition to retired row",
                source="Synthetic source",
                replacement_id="retired-new",
            ),
        )
