"""Independent, deterministic temporal capability fixture (not a public leaderboard)."""
from pathlib import Path
import hashlib
import json
import random


def generate():
    rng = random.Random(20260912)
    identifiers = list(range(10000, 20000))
    rng.shuffle(identifiers)
    assertions, events, queries = [], [], []
    names = ['Asterbrook', 'Brindlehaven', 'Cobaltford', 'Dunewick', 'Embercrest', 'Fernhollow',
             'Glimmerbay', 'Hazelpoint', 'Irisvale', 'Juniperwatch', 'Kestrelport', 'Larchmere']

    def add(subject, predicate, obj, start='2023-01-01', known='2023-01-01', end=None,
            plane='fact', world='main', perspective='general'):
        aid = f't-{identifiers.pop()}'
        text = f'SYNTHETIC BENCHMARK: {subject} {predicate} {obj}.'
        assertions.append(dict(id=aid, subject=subject, predicate=predicate, object=obj,
            valid_from=start, valid_to=end, recorded_at=known, plane=plane, world=world,
            perspective=perspective, summary=text,
            evidence=[dict(title='Synthetic benchmark record', text=text, recorded_at=known, synthetic=True)]))
        return aid

    def event(aid, kind, effective, known, replacement=None):
        events.append(dict(id=f'ev-{len(events):04}', assertion_id=aid, type=kind,
            effective_at=effective, recorded_at=known, replacement_id=replacement,
            reason='Synthetic independently specified lifecycle transition.', source='Benchmark fixture'))

    def q(category, entity, predicate, gold, valid='2023-07-01', known='2023-07-01',
          world='main', plane='fact', perspective='general'):
        queries.append(dict(id=f'q-{len(queries):04}', category=category,
            query=f'{entity} {predicate}', hl_keywords=[predicate], ll_keywords=[entity],
            scope=dict(valid_at=valid, known_at=known, world=world, plane=plane, perspective=perspective),
            gold_assertion_ids=gold))

    for name in names:
        entity = f'{name} Observatory'
        old = add(entity, 'director', 'Mira Holt')
        new = add(entity, 'director', 'Theo Reed', start='2023-06-01', known='2023-06-01')
        event(old, 'supersede', '2023-06-01', '2023-06-01', new)
        q('valid_before_change', entity, 'director', [old], valid='2023-05-31')
        q('valid_after_change', entity, 'director', [new])
        q('exclusive_boundary', entity, 'director', [new], valid='2023-06-01')
        q('known_before_change', entity, 'director', [old], known='2023-05-31')

        storm = f'{name} storm'
        original = add(storm, 'injured count', '12', start='2023-06-01', known='2023-06-01', plane='report')
        corrected = add(storm, 'injured count', '2', start='2023-06-01', known='2023-06-03', plane='report')
        event(original, 'correct', '2023-06-01', '2023-06-03', corrected)
        q('late_correction_before', storm, 'injured count', [original], valid='2023-06-01', known='2023-06-02', plane='report')
        q('late_correction_after', storm, 'injured count', [corrected], valid='2023-06-01', known='2023-06-04', plane='report')

        bridge = f'{name} bridge'
        rumor = add(bridge, 'collapse status', 'collapsed', start='2023-06-01', known='2023-06-01', plane='report')
        event(rumor, 'retract', '2023-06-01', '2023-06-03')
        q('retraction_before', bridge, 'collapse status', [rumor], valid='2023-06-01', known='2023-06-02', plane='report')
        q('retraction_empty', bridge, 'collapse status', [], valid='2023-06-01', known='2023-06-04', plane='report')

        moon = f'{name} moon'
        physical = add(moon, 'shape', 'spherical', plane='fact')
        belief = add(moon, 'shape', 'flat', plane='belief')
        q('plane_fact', moon, 'shape', [physical])
        q('plane_belief', moon, 'shape', [belief], plane='belief')

        capital = f'{name} region'
        main = add(capital, 'capital', 'Northport')
        scenario = add(capital, 'capital', 'Southport', world='counterfactual')
        q('world_main', capital, 'capital', [main])
        q('world_counterfactual', capital, 'capital', [scenario], world='counterfactual')

        harbor = f'{name} harbor'
        municipal = add(harbor, 'opening date', 'June 11', plane='report', perspective='municipal')
        local = add(harbor, 'opening date', 'June 12', plane='report', perspective='local press')
        q('perspective_municipal', harbor, 'opening date', [municipal], plane='report', perspective='municipal')
        q('perspective_press', harbor, 'opening date', [local], plane='report', perspective='local press')

        park = f'{name} park'
        one = add(park, 'reopened on', 'June 5', plane='report')
        two = add(park, 'reopened on', 'June 6', plane='report')
        q('preserve_conflict', park, 'reopened on', [one, two], plane='report')

        launch = f'{name} launch'
        future = add(launch, 'mission status', 'successful', start='2023-06-01', known='2023-06-10', plane='report')
        q('future_knowledge_empty', launch, 'mission status', [], known='2023-06-09', plane='report')
        q('future_knowledge_visible', launch, 'mission status', [future], known='2023-06-10', plane='report')

        trial = f'{name} permit'
        bounded = add(trial, 'access status', 'authorized', end='2023-06-01')
        q('finite_interval_inside', trial, 'access status', [bounded], valid='2023-05-31')
        q('finite_interval_empty', trial, 'access status', [], valid='2023-06-01')

        model = f'{name} gravity'
        classical = add(model, 'model', 'Newtonian approximation', plane='theory', perspective='weak field')
        relativistic = add(model, 'model', 'general relativity', plane='theory', perspective='strong field')
        q('theory_domain_classical', model, 'model', [classical], plane='theory', perspective='weak field')
        q('theory_domain_relativistic', model, 'model', [relativistic], plane='theory', perspective='strong field')

    # Stable randomized IDs/order prevent chronological ID ties from favoring a system.
    rng.shuffle(assertions)
    rng.shuffle(queries)
    return dict(name='Chronoverse temporal capability v1', synthetic=True, seed=20260912,
        disclaimer='Generated structured-data capability diagnostic, not independent public benchmark or extraction evaluation. Gold answers are specified directly by scenario design, never by the implementation under test.',
        assertions=assertions, events=events, queries=queries)


if __name__ == '__main__':
    path = Path(__file__).parent / 'data' / 'temporal-v1.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(generate(), indent=2, ensure_ascii=False)+'\n')
    print(json.dumps(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        assertions=len(generate()['assertions']), queries=len(generate()['queries']))))
