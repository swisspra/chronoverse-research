"""Deterministic synthetic observer-receipt fixture with hand-authored gold labels.

Pre-measurement revision: exact duplicate query scopes were removed before any
retrieval or scoring run. The superseded artifact is preserved as observer-v1-draft.json.
"""
from pathlib import Path
import hashlib
import json


T = "2026-04-01T00:00:00.000000Z"
K = "2026-04-30T23:59:59.999999Z"


def generate():
    assertions, events, receipts, queries = [], [], [], []

    def assertion(aid, subject, predicate, obj, *, valid_from=T, valid_to=None,
                  recorded_at=T, plane="report", world="main", perspective="wire-a"):
        text = f"SYNTHETIC OBSERVER FIXTURE: {subject} {predicate} {obj}."
        assertions.append({"id": aid, "subject": subject, "predicate": predicate,
            "object": obj, "world": world, "plane": plane, "perspective": perspective,
            "valid_from": valid_from, "valid_to": valid_to, "recorded_at": recorded_at,
            "summary": "Synthetic claim for an observer-specific retrieval diagnostic.",
            "evidence": [{"title": "Synthetic passage", "text": text,
                "recorded_at": recorded_at, "synthetic": True}]})

    def event(eid, aid, kind, effective, recorded, replacement=None):
        events.append({"id": eid, "assertion_id": aid, "type": kind,
            "effective_at": effective, "recorded_at": recorded,
            "reason": "Synthetic lifecycle transition.", "source": "Synthetic audit desk",
            "replacement_id": replacement})

    def receipt(rid, observer, kind, item, received, recorded):
        receipts.append({"id": rid, "observer_id": observer, "item_type": kind,
            "item_id": item, "received_at": received, "recorded_at": recorded})

    def query(qid, family, observer, text, valid, known, observed, ga=(), ge=(), gv=(),
              *, world="main", plane="report", perspective="all", rationale):
        # Gold is literal scenario authorship; it is never derived from Store or filtering code.
        queries.append({"id": qid, "family": family, "observer_id": observer,
            "query": text, "scope": {"valid_at": valid, "known_at": known,
                "observer_at": observed, "world": world, "plane": plane,
                "perspective": perspective}, "gold_assertion_ids": list(ga),
            "gold_evidence_ids": list(ge), "gold_event_ids": list(gv),
            "rationale": rationale})

    # Shared synthetic vocabulary is intentionally small; opaque IDs prevent semantic label leakage.
    assertion("oa7k", "Aster ferry", "departure gate", "north", perspective="harbor-wire")
    for o, at in [("observer-red", "2026-04-02T09:00:00.000000Z"),
                  ("observer-blue", "2026-04-05T09:00:00.000000Z")]:
        receipt(f"r-{o[-3:]}-oa7k-a", o, "assertion", "oa7k", at, at)
        receipt(f"r-{o[-3:]}-oa7k-e", o, "evidence", "oa7k-e1", at, at)
    base = [("01","observer-red","2026-04-02T08:59:59.999999Z",(),()),
            ("02","observer-red","2026-04-02T09:00:00.000000Z",("oa7k",),("oa7k-e1",)),
            ("03","observer-blue","2026-04-04T12:00:00.000000Z",(),()),
            ("04","observer-blue","2026-04-05T09:00:00.000000Z",("oa7k",),("oa7k-e1",)),
            ("05","observer-green",K,(),())]
    for n,o,ot,ga,ge in base:
        query("oq"+n,"same_event_different_arrival",o,"Aster ferry departure gate",T,K,ot,ga,ge,
              rationale="Visibility begins at that observer's receipt boundary; an unopened observer stays empty.")

    assertion("pb3m", "Brindle clinic", "open status", "open", perspective="civic-feed")
    receipt("r-red-pb3m-a","observer-red","assertion","pb3m","2026-04-03T10:00:00.000000Z","2026-04-03T10:00:00.000000Z")
    receipt("r-red-pb3m-e","observer-red","evidence","pb3m-e1","2026-04-06T10:00:00.000000Z","2026-04-06T10:00:00.000000Z")
    for n,ot,ga,ge in [("06","2026-04-03T10:00:00.000000Z",("pb3m",),()),
                       ("07","2026-04-06T09:59:59.999999Z",("pb3m",),()),
                       ("08","2026-04-06T10:00:00.000000Z",("pb3m",),("pb3m-e1",))]:
        query("oq"+n,"separate_passage_delivery","observer-red","Brindle clinic open status",T,K,ot,ga,ge,
              rationale="Assertion receipt exposes claim fields; only evidence receipt exposes the answer passage.")
    query("oq09","separate_passage_delivery","observer-blue","Brindle clinic open status",T,K,K,(),(),
          rationale="Global recording does not substitute for an observer receipt.")

    assertion("cx9r","Cobalt storm","injured count","12",recorded_at="2026-04-04T08:00:00.000000Z",perspective="newsdesk")
    assertion("dq2v","Cobalt storm","injured count","2",recorded_at="2026-04-08T08:00:00.000000Z",perspective="newsdesk")
    event("ev-cobalt-correct","cx9r","correct",T,"2026-04-08T08:00:00.000000Z","dq2v")
    for kind,item,at in [("assertion","cx9r","2026-04-04T09:00:00.000000Z"),("evidence","cx9r-e1","2026-04-04T09:00:00.000000Z"),
                         ("event","ev-cobalt-correct","2026-04-09T09:00:00.000000Z"),("assertion","dq2v","2026-04-10T09:00:00.000000Z"),("evidence","dq2v-e1","2026-04-11T09:00:00.000000Z")]:
        receipt("r-red-"+item,"observer-red",kind,item,at,at)
    for kind,item,at in [("assertion","cx9r","2026-04-04T09:00:00.000000Z"),("evidence","cx9r-e1","2026-04-04T09:00:00.000000Z"),("assertion","dq2v","2026-04-08T09:00:00.000000Z"),("evidence","dq2v-e1","2026-04-08T09:00:00.000000Z"),("event","ev-cobalt-correct","2026-04-12T09:00:00.000000Z")]:
        receipt("r-blue-"+item,"observer-blue",kind,item,at,at)
    correction_cases = [
      ("10","observer-red","2026-04-08T23:00:00.000000Z",("cx9r",),("cx9r-e1",),()),
      ("11","observer-red","2026-04-09T09:00:00.000000Z",(),(),("ev-cobalt-correct",)),
      ("12","observer-red","2026-04-10T09:00:00.000000Z",("dq2v",),(),("ev-cobalt-correct",)),
      ("13","observer-red","2026-04-11T09:00:00.000000Z",("dq2v",),("dq2v-e1",),("ev-cobalt-correct",)),
      ("14","observer-blue","2026-04-09T00:00:00.000000Z",("cx9r","dq2v"),("cx9r-e1","dq2v-e1"),()),
      ("15","observer-blue","2026-04-12T09:00:00.000000Z",("dq2v",),("dq2v-e1",),("ev-cobalt-correct",))]
    for n,o,ot,ga,ge,gv in correction_cases:
        query("oq"+n,"delayed_correction",o,"Cobalt storm injured count",T,K,ot,ga,ge,gv,
              rationale="A received correction retires the old claim even when its replacement passage has not arrived; receipt is awareness, not endorsement.")

    assertion("er5n","Dunewick bridge","collapse status","collapsed",recorded_at="2026-04-05T08:00:00.000000Z",perspective="wire-b")
    event("ev-dune-retract","er5n","retract",T,"2026-04-07T08:00:00.000000Z")
    for o, evat in [("observer-red","2026-04-07T09:00:00.000000Z"),("observer-blue","2026-04-10T09:00:00.000000Z")]:
        receipt(f"r-{o[-3:]}-er5n-a",o,"assertion","er5n","2026-04-05T09:00:00.000000Z","2026-04-05T09:00:00.000000Z")
        receipt(f"r-{o[-3:]}-er5n-e",o,"evidence","er5n-e1","2026-04-05T09:00:00.000000Z","2026-04-05T09:00:00.000000Z")
        receipt(f"r-{o[-3:]}-dune-ev",o,"event","ev-dune-retract",evat,evat)
    for n,o,ot,ga,ge,gv in [("16","observer-red","2026-04-07T08:59:59.999999Z",("er5n",),("er5n-e1",),()),
                            ("17","observer-red","2026-04-07T09:00:00.000000Z",(),(),("ev-dune-retract",)),
                            ("18","observer-blue","2026-04-09T12:00:00.000000Z",("er5n",),("er5n-e1",),()),
                            ("19","observer-blue","2026-04-10T09:00:00.000000Z",(),(),("ev-dune-retract",))]:
        query("oq"+n,"delayed_retraction",o,"Dunewick bridge collapse status",T,K,ot,ga,ge,gv,rationale="Retraction affects only observers that received its lifecycle event.")

    assertion("fu8p","Ember archive","permit status","approved",recorded_at=T,perspective="registry")
    receipt("r-red-fu8p-a","observer-red","assertion","fu8p","2026-04-10T12:00:00.000000Z","2026-04-15T12:00:00.000000Z")
    receipt("r-red-fu8p-e","observer-red","evidence","fu8p-e1","2026-04-10T12:00:00.000000Z","2026-04-15T12:00:00.000000Z")
    for n,known,ot,ga,ge in [("20","2026-04-15T11:59:59.999999Z","2026-04-20T00:00:00.000000Z",(),()),
                             ("21","2026-04-15T12:00:00.000000Z","2026-04-10T11:59:59.999999Z",(),()),
                             ("22","2026-04-15T12:00:00.000000Z","2026-04-10T12:00:00.000000Z",("fu8p",),("fu8p-e1",)),
                             ("23","2026-04-14T00:00:00.000000Z",K,(),())]:
        query("oq"+n,"late_receipt_log","observer-red","Ember archive permit status",T,known,ot,ga,ge,
              rationale="Both receipt.recorded_at <= known_at and receipt.received_at <= observer_at are required, even when the receipt was logged after delivery.")

    assertion("gw4t","Fern harbor","opening date","April 18",perspective="municipal")
    assertion("hx6c","Fern harbor","opening date","April 19",perspective="local-press")
    for aid in ("gw4t","hx6c"):
        receipt("r-red-"+aid+"-a","observer-red","assertion",aid,"2026-04-06T12:00:00.000000Z","2026-04-06T12:00:00.000000Z")
        receipt("r-red-"+aid+"-e","observer-red","evidence",aid+"-e1","2026-04-06T12:00:00.000000Z","2026-04-06T12:00:00.000000Z")
    for n,p,ga,ge in [("24","all",("gw4t","hx6c"),("gw4t-e1","hx6c-e1")),("25","municipal",("gw4t",),("gw4t-e1",)),("26","local-press",("hx6c",),("hx6c-e1",))]:
        query("oq"+n,"source_vs_observer","observer-red","Fern harbor opening date",T,K,K,ga,ge,perspective=p,
              rationale="Perspective identifies the source; observer identity remains a separate receipt filter. Conflicting received reports remain visible.")
    query("oq27","source_vs_observer","municipal","Fern harbor opening date",T,K,K,(),(),perspective="municipal",rationale="A source name is not an observer receipt identity.")

    assertion("jy1s","Glimmer rail","service status","running",valid_from="2026-04-01T00:00:00.000000Z",valid_to="2026-04-12T00:00:00.000000Z",perspective="transit-wire")
    receipt("r-red-jy1s-a","observer-red","assertion","jy1s","2026-04-02T00:00:00.000000Z","2026-04-02T00:00:00.000000Z")
    receipt("r-red-jy1s-e","observer-red","evidence","jy1s-e1","2026-04-02T00:00:00.000000Z","2026-04-02T00:00:00.000000Z")
    for n,valid,ga,ge in [("28","2026-04-01T00:00:00.000000Z",("jy1s",),("jy1s-e1",)),("29","2026-04-11T23:59:59.999999Z",("jy1s",),("jy1s-e1",)),("30","2026-04-12T00:00:00.000000Z",(),()),("31","2026-03-31T23:59:59.999999Z",(),())]:
        query("oq"+n,"historical_valid_time","observer-red","Glimmer rail service status",valid,K,K,ga,ge,rationale="Valid time is half-open and independent of observer receipt time.")

    assertion("kz0d","Hazel launch","mission status","successful",recorded_at="2026-05-02T00:00:00.000000Z",perspective="mission-wire")
    receipt("r-red-kz0d-a","observer-red","assertion","kz0d","2026-05-03T00:00:00.000000Z","2026-05-03T00:00:00.000000Z")
    receipt("r-red-kz0d-e","observer-red","evidence","kz0d-e1","2026-05-03T00:00:00.000000Z","2026-05-03T00:00:00.000000Z")
    for n,known,ot,ga,ge in [("32",K,"2026-05-10T00:00:00.000000Z",(),()),("33","2026-05-02T00:00:00.000000Z","2026-05-02T23:00:00.000000Z",(),()),("34","2026-05-03T00:00:00.000000Z","2026-05-03T00:00:00.000000Z",("kz0d",),("kz0d-e1",))]:
        query("oq"+n,"globally_future_unrecorded","observer-red","Hazel launch mission status",T,known,ot,ga,ge,rationale="Future global recording and observer receipt cannot leak into an earlier known snapshot.")

    # Known subject-overlap distractors exercise ordinary world/plane/perspective filters.
    assertion("lm2q","Iris council","chair","Lena",plane="fact",perspective="registry")
    assertion("mn7b","Iris council","chair","Omar",plane="belief",perspective="rumor-desk")
    assertion("np5x","Iris council","chair","Pia",plane="fact",world="scenario-amber",perspective="registry")
    assertion("qr8j","Iris council annex","chair","Rui",plane="fact",perspective="registry")
    for aid in ("lm2q","mn7b","np5x","qr8j"):
        receipt("r-red-"+aid+"-a","observer-red","assertion",aid,"2026-04-02T00:00:00.000000Z","2026-04-02T00:00:00.000000Z")
        receipt("r-red-"+aid+"-e","observer-red","evidence",aid+"-e1","2026-04-02T00:00:00.000000Z","2026-04-02T00:00:00.000000Z")
    filters=[("35","fact","main","all",("lm2q",)),("36","belief","main","all",("mn7b",)),("37","fact","scenario-amber","all",("np5x",)),("38","fact","main","registry",("lm2q",))]
    for n,pl,w,p,ga in filters:
        query("oq"+n,"ordinary_scope_filter","observer-red","Iris council chair",T,K,K,ga,tuple(x+"-e1" for x in ga),world=w,plane=pl,perspective=p,rationale="Observer receipts compose with ordinary world, plane, perspective, and lexical scope filters.")

    # The answer vocabulary exists only in the passage; generic claim metadata cannot answer early.
    assertion("st3f","Bulletin 17","contains update","see passage",perspective="desk-17")
    assertions[-1]["evidence"][0]["text"] = "SYNTHETIC OBSERVER FIXTURE: Juniper reservoir alert level is amber."
    receipt("r-red-st3f-a","observer-red","assertion","st3f","2026-04-13T08:00:00.000000Z","2026-04-13T08:00:00.000000Z")
    receipt("r-red-st3f-e","observer-red","evidence","st3f-e1","2026-04-16T08:00:00.000000Z","2026-04-16T08:00:00.000000Z")
    query("oq39","answer_only_in_delayed_passage","observer-red","Juniper reservoir amber alert",T,K,"2026-04-15T23:59:59.999999Z",(),(),rationale="Received generic claim metadata contains none of the answer terms, so the answer remains empty before passage delivery.")
    query("oq40","answer_only_in_delayed_passage","observer-red","Juniper reservoir amber alert",T,K,"2026-04-16T08:00:00.000000Z",("st3f",),("st3f-e1",),rationale="The delayed passage supplies the only answer-bearing text.")

    # Evidence may arrive through a passage channel before its parent assertion envelope.
    assertion("tu6h","Digest 24","contains update","see passage",perspective="desk-24")
    assertions[-1]["evidence"][0]["text"] = "SYNTHETIC OBSERVER FIXTURE: Kestrel ridge wind speed is 40 knots."
    receipt("r-blue-tu6h-e","observer-blue","evidence","tu6h-e1","2026-04-14T08:00:00.000000Z","2026-04-14T08:00:00.000000Z")
    query("oq41","evidence_without_assertion","observer-blue","Kestrel ridge wind 40 knots",T,K,K,(),("tu6h-e1",),rationale="Evidence receipt exposes the passage, but no assertion receipt exposes the parent claim fields.")

    # Event effective time, event recording, and per-observer receipt are three independent axes.
    assertion("vw9a","Larch terminal","operator","Ava",plane="fact",perspective="registry")
    assertion("wx2e","Larch terminal","operator","Bo",valid_from="2026-04-10T00:00:00.000000Z",recorded_at="2026-04-11T00:00:00.000000Z",plane="fact",perspective="registry")
    event("ev-larch-supersede","vw9a","supersede","2026-04-10T00:00:00.000000Z","2026-04-12T00:00:00.000000Z","wx2e")
    for kind,item,at in [("assertion","vw9a","2026-04-02T00:00:00.000000Z"),("evidence","vw9a-e1","2026-04-02T00:00:00.000000Z"),
                         ("assertion","wx2e","2026-04-11T00:00:00.000000Z"),("evidence","wx2e-e1","2026-04-11T00:00:00.000000Z"),
                         ("event","ev-larch-supersede","2026-04-15T00:00:00.000000Z")]:
        receipt("r-red-"+item,"observer-red",kind,item,at,at)
    query("oq42","historical_event_receipt","observer-red","Larch terminal operator","2026-04-09T23:59:59.999999Z",K,K,("vw9a",),("vw9a-e1",),("ev-larch-supersede",),plane="fact",rationale="After event receipt, the old assertion remains valid immediately before the event effective boundary.")
    query("oq43","historical_event_receipt","observer-red","Larch terminal operator","2026-04-10T00:00:00.000000Z",K,"2026-04-14T23:59:59.999999Z",("vw9a","wx2e"),("vw9a-e1","wx2e-e1"),(),plane="fact",rationale="Before event receipt, both received assertions remain available at the later valid time.")
    query("oq44","historical_event_receipt","observer-red","Larch terminal operator","2026-04-10T00:00:00.000000Z",K,"2026-04-15T00:00:00.000000Z",("wx2e",),("wx2e-e1",),("ev-larch-supersede",),plane="fact",rationale="At event receipt, supersession applies from its earlier effective time.")
    query("oq45","historical_event_receipt","observer-red","Larch terminal operator","2026-04-09T00:00:00.000000Z","2026-04-11T23:59:59.999999Z",K,("vw9a",),("vw9a-e1",),(),plane="fact",rationale="An event not yet globally recorded cannot affect an earlier known snapshot, even after later observer time.")

    # Five distinct cutoffs round out coverage without repeated observer/query/scope tuples.
    query("oq46","same_event_different_arrival","observer-red","Aster ferry departure gate",T,"2026-04-02T08:59:59.999999Z",K,(),(),rationale="An observer receipt cannot appear before its own audit recording cutoff.")
    query("oq47","separate_passage_delivery","observer-red","Brindle clinic open status",T,"2026-04-05T00:00:00.000000Z",K,("pb3m",),(),rationale="The assertion is recorded and received while its evidence remains unavailable.")
    query("oq48","delayed_correction","observer-blue","Cobalt storm injured count",T,"2026-04-11T00:00:00.000000Z",K,("cx9r","dq2v"),("cx9r-e1","dq2v-e1"),(),rationale="Both conflicting reports remain until this observer receives the correction event.")
    query("oq49","historical_valid_time","observer-red","Glimmer rail service status","2026-04-06T00:00:00.000000Z","2026-04-02T00:00:00.000000Z","2026-04-02T00:00:00.000000Z",("jy1s",),("jy1s-e1",),rationale="Historical valid time composes with exact receipt and recording boundaries.")
    query("oq50","ordinary_scope_filter","observer-red","Iris council chair",T,K,K,(),(),world="scenario-amber",plane="belief",rationale="Known subject-overlap distractors still fail when world and plane filters do not jointly match.")

    assertion_ids = {a["id"] for a in assertions}
    evidence_ids = {a["id"] + "-e1" for a in assertions}
    event_ids = {e["id"] for e in events}
    item_ids = assertion_ids | evidence_ids | event_ids
    assert len({r["id"] for r in receipts}) == len(receipts)
    assert all(r["item_id"] in item_ids for r in receipts)
    assert all(r["received_at"] <= r["recorded_at"] for r in receipts)
    assert len({(q["observer_id"], q["query"], json.dumps(q["scope"], sort_keys=True)) for q in queries}) == len(queries)

    return {"assertions": assertions, "events": events, "receipts": receipts, "queries": queries}


if __name__ == "__main__":
    path = Path(__file__).parent / "data" / "observer-v1.json"
    payload = generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "assertions": len(payload["assertions"]), "events": len(payload["events"]),
        "receipts": len(payload["receipts"]), "queries": len(payload["queries"])}))
