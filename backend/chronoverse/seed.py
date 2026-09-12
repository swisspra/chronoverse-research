"""Synthetic fixtures; historical beliefs are assertions by a perspective, not past physical truth."""
from .models import AssertionInput, EventInput


def populate(store):
    def add(id, subject, predicate, object, *, plane="fact", perspective="general", world="main", valid_from="2026-01-01", recorded_at="2026-01-01", summary="", valid_to=None):
        store.add_assertion(AssertionInput(id=id, subject=subject, predicate=predicate, object=object, plane=plane, world=world, perspective=perspective, valid_from=valid_from, valid_to=valid_to, recorded_at=recorded_at, summary=summary, evidence=[{"title": "Synthetic demo evidence", "text": f"SYNTHETIC DEMO — not a real news report or historical primary source. {subject} {predicate} {object}. {summary}", "recorded_at": recorded_at, "synthetic": True}]))

    add("fact-director-old", "Harbor Institute", "director", "Ada Chen", summary="Appointment bulletin names Ada Chen as the director.")
    add("fact-director-new", "Harbor Institute", "director", "Bea Rivera", valid_from="2026-07-01", recorded_at="2026-07-10", summary="Appointment effective July 1; recorded July 10.")
    add("fact-location", "Harbor Institute", "located in", "Meridian", summary="Entity connector for the graph view.")
    add("news-initial", "Meridian storm", "injured count", "12", plane="report", perspective="newsdesk", valid_from="2026-09-01", recorded_at="2026-09-01", summary="Initial injury count reported by the synthetic newsdesk. This is a report claim, not an adjudicated fact.")
    add("news-corrected", "Meridian storm", "injured count", "2", plane="report", perspective="newsdesk", valid_from="2026-09-01", recorded_at="2026-09-03", summary="Correction learned two days later: ten people had not been injured.")
    add("news-location", "Meridian storm", "occurred in", "Meridian", plane="report", perspective="newsdesk", valid_from="2026-09-01", recorded_at="2026-09-01")
    add("news-disputed-a", "Meridian bridge", "reopened on", "September 10", plane="report", perspective="wire", valid_from="2026-09-10", recorded_at="2026-09-10", summary="A synthetic wire source reports the reopening date.")
    add("news-disputed-b", "Meridian bridge", "reopened on", "September 11", plane="report", perspective="wire", valid_from="2026-09-10", recorded_at="2026-09-11", summary="A later report does not automatically become the canonical truth.")
    add("news-retracted", "Meridian storm", "caused", "dam collapse", plane="report", perspective="wire", valid_from="2026-09-01", recorded_at="2026-09-01", summary="An unverified source reports a dam collapse; corroboration is pending.")
    add("earth-shape-fact", "Earth", "shape", "approximately an oblate spheroid", valid_from="1900-01-01", recorded_at="2026-01-01", summary="Synthetic educational representation of established physical knowledge; Earth did not physically change from flat to round.")
    add("earth-flat-belief", "Earth", "shape", "flat", plane="belief", perspective="fictional historical community", valid_from="1400-01-01", valid_to="1700-01-01", recorded_at="2026-01-01", summary="Fictional historical belief held by a named community; not a claim that everyone once believed this. Valid time describes belief scope; recorded time is when this demo ingested it.")
    add("earth-flat-contemporary", "Earth", "shape", "flat", plane="belief", perspective="fictional flat-earth group", summary="Synthetic contemporary belief assertion for showing plane isolation; not a physical fact.")
    add("theory-newton", "gravity", "model", "Newtonian gravitation", plane="theory", perspective="classical mechanics", valid_from="1687-01-01", recorded_at="2026-01-01", summary="Useful approximation for weak fields and low velocities; remains active within this scope.")
    add("theory-relativity", "gravity", "model", "general relativity", plane="theory", perspective="relativistic physics", valid_from="1915-01-01", recorded_at="2026-01-01", summary="Broader predictive model of gravitation. Does not make every Newtonian calculation useless.")
    add("forecast-weather", "Meridian", "forecast rainfall", "80 mm", plane="forecast", perspective="weather model", valid_from="2026-09-12", recorded_at="2026-09-11", summary="Prediction, not an observed fact.")
    add("scenario-director", "Harbor Institute", "director", "Cy Morgan", plane="fact", world="alternate", summary="Counterfactual world; must never leak into main-world retrieval.")

    for id, target, type, effective_at, recorded_at, replacement_id, reason in [
        ("event-director", "fact-director-old", "supersede", "2026-07-01", "2026-07-10", "fact-director-new", "New appointment effective July 1, learned July 10."),
        ("event-news-correction", "news-initial", "correct", "2026-09-01", "2026-09-03", "news-corrected", "Initial count included ten uninjured people."),
        ("event-news-retraction", "news-retracted", "retract", "2026-09-01", "2026-09-02", None, "Source withdrew the unsupported dam-collapse rumor."),
    ]:
        store.add_event(target, EventInput(id=id, type=type, effective_at=effective_at, recorded_at=recorded_at, replacement_id=replacement_id, reason=reason, source="Synthetic demo lifecycle bulletin"))


EVALUATION_CASES = [
    {"name": "Late appointment: earlier knowledge", "request": {"query": "Harbor director", "plane": "fact", "valid_at": "2026-07-05", "known_at": "2026-07-06"}, "expected": ["fact-director-old"], "forbidden": ["fact-director-new", "scenario-director"], "explanation": "A replacement learned July 10 cannot change a July 6 knowledge snapshot."},
    {"name": "Late appointment: corrected knowledge", "request": {"query": "Harbor director", "plane": "fact", "valid_at": "2026-07-05", "known_at": "2026-07-11"}, "expected": ["fact-director-new"], "forbidden": ["fact-director-old", "scenario-director"], "explanation": "Once known, supersession closes the original fact at July 1."},
    {"name": "News before correction", "request": {"query": "Meridian injured", "plane": "report", "valid_at": "2026-09-01", "known_at": "2026-09-02"}, "expected": ["news-initial"], "forbidden": ["news-corrected", "news-retracted"], "explanation": "The correction is unknown; the retracted rumor is already excluded."},
    {"name": "News after correction", "request": {"query": "Meridian injured", "plane": "report", "valid_at": "2026-09-01", "known_at": "2026-09-04"}, "expected": ["news-corrected"], "forbidden": ["news-initial", "news-retracted"], "explanation": "Same valid date, later knowledge: corrected count is returned with provenance."},
    {"name": "Belief is not physical fact", "request": {"query": "Earth shape", "plane": "fact"}, "expected": ["earth-shape-fact"], "forbidden": ["earth-flat-belief", "earth-flat-contemporary"], "explanation": "Flat Earth remains a scoped belief claim, never a formerly true physical fact."},
    {"name": "Conflicting reports stay visible", "request": {"query": "Meridian bridge", "plane": "report", "perspective": "wire"}, "expected": ["news-disputed-a", "news-disputed-b"], "forbidden": ["news-retracted"], "explanation": "Two active incompatible reports remain visible; recency does not resolve truth."},
]
