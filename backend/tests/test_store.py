import sqlite3

import pytest
from pydantic import ValidationError

from chronoverse.models import AssertionInput, EventInput, QueryRequest
from chronoverse.store import Store


def assertion(id="old", **kw):
    data = dict(id=id, subject="Harbor", predicate="director", object="Ada", valid_from="2026-01-01", recorded_at="2026-01-01", evidence=[dict(title="Synthetic bulletin", text="Synthetic: Ada directs Harbor", synthetic=True)])
    data.update(kw)
    return AssertionInput(**data)


def query(store, **kw):
    data = dict(query="Harbor", valid_at="2026-09-12", known_at="2026-09-12")
    data.update(kw)
    return store.query(QueryRequest(**data))


def ids(result):
    return {a["id"] for a in result["results"]}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.sqlite3", seed=False)
    yield s
    s.close()


def test_valid_time_half_open_and_future_knowledge_hidden(store):
    store.add_assertion(assertion(valid_to="2026-07-01"))
    assert ids(query(store, valid_at="2026-06-30")) == {"old"}
    assert ids(query(store, valid_at="2026-07-01")) == set()
    store.add_assertion(assertion("late", object="Bea", recorded_at="2026-08-01"))
    assert "late" not in ids(query(store, known_at="2026-07-31"))


def test_late_supersession_does_not_rewrite_earlier_knowledge(store):
    store.add_assertion(assertion())
    store.add_assertion(assertion("new", object="Bea", valid_from="2026-07-01", recorded_at="2026-07-10"))
    store.add_event("old", EventInput(id="switch", type="supersede", effective_at="2026-07-01", recorded_at="2026-07-10", reason="Appointment learned late", source="Synthetic appointment", replacement_id="new"))
    assert ids(query(store, valid_at="2026-07-05", known_at="2026-07-06")) == {"old"}
    assert ids(query(store, valid_at="2026-07-01", known_at="2026-07-11")) == {"new"}
    before = query(store, valid_at="2026-06-30", known_at="2026-07-11")["results"]
    assert [a["id"] for a in before] == ["old"]
    assert before[0]["status"] == "active"
    detail = store.get_assertion("old", known_at="2026-07-06", valid_at="2026-07-05")
    assert detail["events"] == []
    assert detail["effective_valid_to"] is None


def test_late_correction_preserves_what_was_known(store):
    store.add_assertion(assertion(plane="report", predicate="injured", object="12", valid_from="2026-09-01", recorded_at="2026-09-01"))
    store.add_assertion(assertion("corrected", plane="report", predicate="injured", object="2", valid_from="2026-09-01", recorded_at="2026-09-03"))
    store.add_event("old", EventInput(type="correct", effective_at="2026-09-01", recorded_at="2026-09-03", reason="Initial count included uninjured people", source="Synthetic correction", replacement_id="corrected"))
    earlier = query(store, valid_at="2026-09-01", known_at="2026-09-02")
    assert ids(earlier) == {"old"}
    assert earlier["results"][0]["events"] == []
    later = query(store, valid_at="2026-09-01", known_at="2026-09-04")
    assert ids(later) == {"corrected"}
    history = query(store, valid_at="2026-09-01", known_at="2026-09-04", include_retired=True)
    assert ids(history) == {"old", "corrected"}
    assert next(a for a in history["results"] if a["id"] == "old")["status"] == "corrected"


def test_retraction_does_not_hide_prior_knowledge(store):
    store.add_assertion(assertion())
    store.add_event("old", EventInput(type="retract", effective_at="2026-01-01", recorded_at="2026-05-01", reason="Evidence withdrawn", source="Synthetic source"))
    assert ids(query(store, known_at="2026-04-30")) == {"old"}
    assert ids(query(store, known_at="2026-05-01")) == set()


def test_filters_apply_before_ranking_and_graph_and_conflicts(store):
    store.add_assertion(assertion())
    store.add_assertion(assertion("foreign", world="scenario", object="Mallory"))
    store.add_assertion(assertion("belief", plane="belief", object="Cy"))
    store.add_assertion(assertion("private", perspective="observer", object="Dee"))
    result = query(store, world="main", plane="fact", perspective="general")
    assert ids(result) == {"old"}
    assert {e["assertion_id"] for e in result["graph"]["edges"]} == {"old"}
    assert result["conflicts"] == []


def test_conflicting_objects_preserved_no_recency_winner(store):
    store.add_assertion(assertion())
    store.add_assertion(assertion("other", object="Bea", recorded_at="2026-02-01"))
    result = query(store)
    assert ids(result) == {"old", "other"}
    assert set(result["conflicts"][0]["assertion_ids"]) == {"old", "other"}
    assert all(a["status"] == "active" for a in result["results"])


def test_evidence_recorded_later_cannot_leak_to_search_or_detail(store):
    store.add_assertion(assertion(evidence=[dict(title="Early", text="Synthetic report", recorded_at="2026-01-01"), dict(title="Late secret", text="unicornspecific", recorded_at="2026-05-01")]))
    earlier = query(store, query="unicornspecific", known_at="2026-04-01")
    assert ids(earlier) == set()
    detail = store.get_assertion("old", known_at="2026-04-01")
    assert [e["title"] for e in detail["evidence"]] == ["Early"]
    assert ids(query(store, query="unicornspecific", known_at="2026-05-01")) == {"old"}


def test_idempotency_durability_and_immutable_sql(tmp_path):
    path = tmp_path / "durable.sqlite3"
    s = Store(path, seed=False)
    first = s.add_assertion(assertion())
    assert s.add_assertion(assertion())["id"] == first["id"]
    with pytest.raises(ValueError, match="already exists"):
        s.add_assertion(assertion(object="Changed"))
    event = EventInput(id="retired", type="retract", effective_at="2026-01-01", recorded_at="2026-05-01", reason="Withdrawn", source="Synthetic")
    assert s.add_event("old", event) == s.add_event("old", event)
    s.close()
    s = Store(path, seed=False)
    assert s.meta()["counts"] == {"assertions": 1, "events": 1}
    assert s.get_assertion("old")["status"] == "retracted"
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE assertions SET payload = '{}' WHERE id = 'old'")
    s.close()


def test_events_cannot_reference_different_scope_or_missing_assertion(store):
    store.add_assertion(assertion())
    store.add_assertion(assertion("other", world="other"))
    with pytest.raises(ValueError, match="scope"):
        store.add_event("old", EventInput(type="correct", effective_at="2026-01-01", recorded_at="2026-03-01", reason="reason", source="source", replacement_id="other"))
    with pytest.raises(KeyError):
        store.add_event("missing", EventInput(type="retract", effective_at="2026-01-01", reason="reason", source="source"))


@pytest.mark.parametrize("kwargs", [{"valid_from":"nonsense"}, {"valid_to":"2025-01-01"}, {"plane":"truth"}, {"subject":" "}, {"evidence":[]}])
def test_invalid_assertions_rejected(kwargs):
    with pytest.raises(ValidationError):
        assertion(**kwargs)


def test_invalid_query_and_event_rejected():
    for kwargs in ({"limit":0}, {"limit":101}, {"known_at":"bad"}, {"plane":"magic"}):
        with pytest.raises(ValidationError):
            QueryRequest(**kwargs)
    with pytest.raises(ValidationError):
        EventInput(type="correct", effective_at="2026-01-01", reason="r", source="s")


def test_seed_replays_safely_and_evaluation_passes(tmp_path):
    path = tmp_path / "seed.sqlite3"
    first = Store(path)
    count = first.meta()["counts"]
    evaluation = first.evaluate()
    assert evaluation["summary"]["chronoverse_passed"] == evaluation["summary"]["cases"]
    assert evaluation["summary"]["baseline_passed"] < evaluation["summary"]["cases"]
    first.close()
    second = Store(path)
    assert second.meta()["counts"] == count
    assert second.query(QueryRequest(query="Earth", plane="fact"))["results"]
    second.close()


def test_concurrent_store_connections_can_replay_same_write(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    path = tmp_path / "concurrent.sqlite3"
    setup = Store(path, seed=False)
    setup.close()
    stores = [Store(path, seed=False) for _ in range(8)]
    barrier = Barrier(len(stores))
    def append(store):
        barrier.wait()
        return store.add_assertion(assertion())["id"]
    try:
        with ThreadPoolExecutor(max_workers=len(stores)) as pool:
            assert list(pool.map(append, stores)) == ["old"] * len(stores)
        assert stores[0].meta()["counts"]["assertions"] == 1
    finally:
        for store in stores:
            store.close()


def test_fixture_initial_evidence_does_not_narrate_future_events(tmp_path):
    store = Store(tmp_path / "as-known.sqlite3")
    try:
        old = store.get_assertion("fact-director-old", valid_at="2026-07-05", known_at="2026-07-06")
        initial = store.get_assertion("news-initial", valid_at="2026-09-01", known_at="2026-09-01")
        rumor = store.get_assertion("news-retracted", valid_at="2026-09-01", known_at="2026-09-01")
        assert "learned ten days late" not in old["summary"]
        assert "subsequently corrected" not in initial["summary"]
        assert "withdrawn" not in rumor["summary"]
        assert all(not item["events"] for item in (old, initial, rumor))
    finally:
        store.close()


def test_graph_support_does_not_jump_between_worlds_or_planes(store):
    store.add_assertion(assertion(evidence=[dict(title="Synthetic", text="appointmentspecial")]))
    store.add_assertion(assertion("other-world", world="alternate"))
    store.add_assertion(assertion("other-plane", plane="belief"))
    result = query(store, query="appointmentspecial", world="all", plane="all")
    assert ids(result) == {"old"}


def test_replacement_cycles_are_rejected(store):
    store.add_assertion(assertion())
    store.add_assertion(assertion("new", object="Bea"))
    store.add_event("old", EventInput(type="correct", effective_at="2026-01-01", recorded_at="2026-02-01", reason="Corrected", source="Synthetic", replacement_id="new"))
    with pytest.raises(ValueError, match="cycle"):
        store.add_event("new", EventInput(type="correct", effective_at="2026-01-01", recorded_at="2026-03-01", reason="Reverses correction", source="Synthetic", replacement_id="old"))
