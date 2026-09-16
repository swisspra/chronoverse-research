"""Score all five as-of pilot arms: accuracy, future leak, abstention, context starvation.

Gold is the price range printed in the issue that was current at the asked date, taken
from the parsed grid - no model judged it.
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path('/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot')
ARMS = ('lightrag_hybrid', 'static', 'postfilt', 'asof', 'static_item', 'asof_item')
LABEL = {'static': 'one static index, no time awareness',
         'postfilt': 'retrieve first, then drop future issues',
         'asof': 'restrict to issues known at the asked date, then retrieve',
         'static_item': 'latest version per series over the whole corpus',
         'asof_item': 'restrict to known issues, then latest version per series',
         'lightrag_hybrid': 'LightRAG 1.5.7 hybrid, its own graph and chunking'}

questions = {q['id']: q for q in (json.loads(line) for line in
                                  (ROOT / 'icis-questions.jsonl').read_text().splitlines())}
rows = []
for name in ('arm-results-v3.jsonl', 'arm-results-v4.jsonl', 'lightrag-results-hybrid.jsonl'):
    path = ROOT / name
    if path.exists():
        rows += [json.loads(line) for line in path.read_text().splitlines()]

prices = [json.loads(line) for line in (ROOT / 'pe-asia-2025-prices.jsonl').read_text().splitlines()]
by_series = defaultdict(dict)
for price in prices:
    by_series[(price['grade'].upper().strip(), price['route'].upper())][price['issue']] = price['week_price']


def visible_values(question):
    issues = {i.replace('pe-', '') for i in question['visible_issue_ids']}
    return {value for issue, value in by_series.get((question['grade'], question['route']), {}).items()
            if issue in issues}


RANGE = re.compile(r'\b(\d{3,4}(?:\.\d+)?-\d{3,4}(?:\.\d+)?)\b')
acc = {arm: defaultdict(int) for arm in ARMS}
per_series = defaultdict(lambda: defaultdict(int))
for row in rows:
    question = questions.get(row['question_id'])
    if question is None or row['arm'] not in acc:
        continue
    arm, text = row['arm'], row['answer']
    gold = question['expected_answers'][0]
    seen = visible_values(question)
    future_values = {v for v in question['future_leak_values'] if v != gold and v not in seen}
    stated = set(RANGE.findall(text))
    abstained = text.strip().startswith('INSUFFICIENT EVIDENCE')
    bucket = acc[arm]
    bucket['n'] += 1
    correct = int(gold in stated)
    bucket['correct'] += correct
    bucket['abstained'] += int(abstained)
    bucket['future_leak'] += int(bool(stated & future_values))
    bucket['cited_future_issue'] += int(any(i in question['future_issue_ids'] for i in row['context_issues']))
    bucket['empty_context'] += int(not row['context_issues'])
    bucket['gold_issue_in_context'] += int(question['gold_issue_id'] in row['context_issues'])
    bucket['prompt_tokens'] += row.get('usage', {}).get('prompt_tokens', 0)
    series = f"{question['grade']} {question['route']}"
    per_series[series][arm] += correct
    per_series[series]['n_' + arm] += 1

print(f'{len(rows)} answers over {len({r["question_id"] for r in rows})} questions\n')
head = (f"{'arm':<12}{'retrieval policy':<52}{'correct':>9}{'gold in ctx':>13}"
        f"{'wrong era':>11}{'abstained':>11}{'ctx tokens':>12}")
print(head + '\n' + '-' * len(head))
for arm in ARMS:
    b = acc[arm]
    if not b['n']:
        continue
    pct = lambda key: f"{100 * b[key] / b['n']:5.1f}%"
    print(f"{arm:<12}{LABEL[arm]:<52}{pct('correct'):>9}{pct('gold_issue_in_context'):>13}"
          f"{pct('future_leak'):>11}{pct('abstained'):>11}{b['prompt_tokens'] // max(1, b['n']):>12}")

print('\ncontext containing at least one future issue:',
      {arm: f"{100 * acc[arm]['cited_future_issue'] / max(1, acc[arm]['n']):.0f}%" for arm in ARMS if acc[arm]['n']})

print('\nper series (correct / n):')
present = [a for a in ARMS if acc[a]['n']]
print(f"{'series':<46}" + ''.join(f'{a:>13}' for a in present))
for series, counts in sorted(per_series.items(), key=lambda kv: -kv[1]['n_' + present[0]]):
    print(f'{series:<46}' + ''.join(f"{str(counts[a]) + '/' + str(counts['n_' + a]):>13}" for a in present))

if '--mcnemar' in sys.argv:
    from math import comb
    answers = defaultdict(dict)
    for row in rows:
        question = questions.get(row['question_id'])
        if question is None:
            continue
        answers[row['question_id']][row['arm']] = int(
            question['expected_answers'][0] in set(RANGE.findall(row['answer'])))
    print('\nexact McNemar, two-sided:')
    for a, b in (('asof', 'asof_item'), ('static', 'asof_item'), ('static_item', 'asof_item'),
                 ('static', 'asof'), ('static', 'postfilt'),
                 ('lightrag_hybrid', 'static'), ('lightrag_hybrid', 'asof'),
                 ('lightrag_hybrid', 'asof_item')):
        pairs = [(v[a], v[b]) for v in answers.values() if a in v and b in v]
        n01 = sum(1 for x, y in pairs if x == 0 and y == 1)
        n10 = sum(1 for x, y in pairs if x == 1 and y == 0)
        n = n01 + n10
        p = 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(min(n01, n10) + 1)) / 2 ** n)
        print(f'  {a:<12} vs {b:<12} {b} better on {n01}, worse on {n10}, p = {p:.4f}')
