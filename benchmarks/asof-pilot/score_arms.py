"""Score the ICIS as-of pilot: accuracy, future leak, abstention, context starvation.

Gold is the price range printed in the issue that was current at the asked date, taken
from the parsed grid - no model judged it.
"""
import json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path('/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot')
ARMS = ('static', 'postfilt', 'asof')
LABEL = {'static': 'one static index, no time awareness',
         'postfilt': 'retrieve first, then drop future issues',
         'asof': 'restrict to issues known at the asked date, then retrieve'}

questions = {q['id']: q for q in (json.loads(line) for line in
                                  (ROOT / 'icis-questions.jsonl').read_text().splitlines())}
rows = [json.loads(line) for line in (ROOT / 'arm-results.jsonl').read_text().splitlines()]

prices = [json.loads(line) for line in (ROOT / 'pe-asia-2025-prices.jsonl').read_text().splitlines()]
by_series = defaultdict(dict)
for price in prices:
    key = (price['grade'].upper().strip(), price['route'].upper())
    by_series[key][price['issue']] = price['week_price']


def visible_values(question):
    key = (question['grade'], question['route'])
    issues = {i.replace('pe-', '') for i in question['visible_issue_ids']}
    return {value for issue, value in by_series.get(key, {}).items() if issue in issues}

RANGE = re.compile(r'\b(\d{3,4}(?:\.\d+)?-\d{3,4}(?:\.\d+)?)\b')
acc = {arm: defaultdict(int) for arm in ARMS}
answered = {arm: 0 for arm in ARMS}
for row in rows:
    question = questions.get(row['question_id'])
    if question is None:
        continue
    arm, text = row['arm'], row['answer']
    gold = question['expected_answers'][0]
    seen = visible_values(question)
    future_values = {v for v in question['future_leak_values'] if v != gold and v not in seen}
    stated = set(RANGE.findall(text))
    abstained = text.strip().startswith('INSUFFICIENT EVIDENCE')
    bucket = acc[arm]
    bucket['n'] += 1
    bucket['correct'] += int(gold in stated)
    bucket['abstained'] += int(abstained)
    bucket['future_leak'] += int(bool(stated & future_values))
    bucket['cited_future_issue'] += int(any(i in question['future_issue_ids'] for i in row['context_issues']))
    bucket['empty_context'] += int(not row['context_issues'])
    if not abstained:
        answered[arm] += 1

print(f'{len(rows)} answers over {len({r["question_id"] for r in rows})} questions\n')
head = f"{'arm':<10}{'retrieval policy':<46}{'correct':>9}{'wrong era':>11}{'abstained':>11}{'no context':>12}"
print(head + '\n' + '-' * len(head))
for arm in ARMS:
    b = acc[arm]
    if not b['n']:
        continue
    pct = lambda key: f"{100 * b[key] / b['n']:5.1f}%"
    print(f"{arm:<10}{LABEL[arm]:<46}{pct('correct'):>9}{pct('future_leak'):>11}"
          f"{pct('abstained'):>11}{pct('empty_context'):>12}")
print('\ncontext containing at least one future issue:',
      {arm: f"{100 * acc[arm]['cited_future_issue'] / max(1, acc[arm]['n']):.0f}%" for arm in ARMS})
print('answers actually given (not abstained):', answered)
