"""Build as-of questions whose gold comes from the ICIS grid itself, not from a model.

The corpus carries a real knowledge clock: the assessment for a given week only exists
in the issue published that week. Asking "as of date D" therefore has one correct answer
per series - the latest issue published on or before D - and every later issue in the
corpus is a future leak.
"""
import json, random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path('/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot')
D = lambda s: date(*map(int, s.split('-')))
SEED = 20260913
SAMPLE = 100

rows = [json.loads(line) for line in (ROOT / 'pe-asia-2025-prices.jsonl').read_text().splitlines()]
for row in rows:
    row['key'] = (row['grade'].upper().strip(), row['route'].upper())

series = defaultdict(dict)
for row in rows:
    if row['issue'] in series[row['key']] and series[row['key']][row['issue']]['week_price'] != row['week_price']:
        raise SystemExit(f"ambiguous series {row['key']} in {row['issue']}: two different prices")
    series[row['key']][row['issue']] = row

questions = []
for key, by_issue in series.items():
    grade, route = key
    dates = sorted(by_issue)
    for index, issue in enumerate(dates):
        if index == 0:
            continue  # need at least one earlier issue so "as of" is not the first record
        asked_on = D(issue) + timedelta(days=2)  # two days after publication, before the next issue
        later = [d for d in dates if D(d) > asked_on]
        questions.append({
            'id': f'icis-{grade.lower().replace(" ", "-")}-{route.lower().replace(" ", "-")}-{issue}',
            'series': f'{grade} {route}',
            'grade': grade, 'route': route,
            'question': f'As of {asked_on.isoformat()}, what is the most recent ICIS spot price range '
                        f'for {grade.title()} {route.title()} in USD/tonne?',
            'known_at': asked_on.isoformat(),
            'valid_issue': issue,
            'expected_answers': [by_issue[issue]['week_price']],
            'gold_issue_id': f'pe-{issue}',
            'visible_issue_ids': [f'pe-{d}' for d in dates if D(d) <= asked_on],
            'future_issue_ids': [f'pe-{d}' for d in later],
            'future_leak_values': sorted({by_issue[d]['week_price'] for d in later}),
            'family': 'as_of_latest',
        })

rng = random.Random(SEED)
rng.shuffle(questions)
sample = sorted(questions[:SAMPLE], key=lambda q: q['id'])
(ROOT / 'icis-questions.jsonl').write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in sample))

distinct_future = sum(1 for q in sample if any(v != q['expected_answers'][0] for v in q['future_leak_values']))
print(json.dumps({'built': len(questions), 'sampled': len(sample), 'seed': SEED,
                  'series': len(series),
                  'questions_where_a_later_issue_differs': distinct_future,
                  'output': str(ROOT / 'icis-questions.jsonl')}))
for q in sample[:3]:
    print(' ', q['id'], '|', q['question'][:96], '| gold', q['expected_answers'][0],
          '| visible', len(q['visible_issue_ids']), '| future', len(q['future_issue_ids']))
