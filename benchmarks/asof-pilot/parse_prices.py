"""Parse the weekly price grid out of each PE Asia-Pacific issue.

Each assessment row looks like:
    CFR China USD/tonne -15 1085-1120 -15 1100-1150 49.21-50.80
    <route>   <unit>    <chg> <this week>  <chg> <last week>  <other currency>
The grade comes from the nearest preceding section heading.
"""
import json, re
from pathlib import Path

SRC = Path('/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot/pe-asia-2025.jsonl')
OUT = Path('/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot/pe-asia-2025-prices.jsonl')

GRADE = re.compile(r'^(LDPE|LLDPE|HDPE)\b[^\n]{0,60}', re.I)
ROW = re.compile(r'^(?P<route>CFR [A-Za-z ]+?(?:All Origins|Dutiable\*?|Non-Dutiable\*?|All|)?)\s+'
                 r'USD/tonne\s+(?P<chg1>n/c|[-+]?\d+(?:\.\d+)?)\s+(?P<now>\d{3,4}(?:\.\d+)?-\d{3,4}(?:\.\d+)?)\s+'
                 r'(?P<chg2>n/c|[-+]?\d+(?:\.\d+)?)\s+(?P<prev>\d{3,4}(?:\.\d+)?-\d{3,4}(?:\.\d+)?)')

rows = []
for line in SRC.read_text().splitlines():
    issue = json.loads(line)
    grade = None
    for raw in issue['text'].split('\n'):
        text = raw.strip()
        if GRADE.match(text):
            grade = ' '.join(text.split()).rstrip(':')[:48]
        hit = ROW.match(text)
        if hit and grade:
            rows.append({'issue': issue['published'], 'grade': grade,
                         'route': ' '.join(hit.group('route').split()),
                         'week_price': hit.group('now'), 'prior_price': hit.group('prev'),
                         'change': hit.group('chg1')})

OUT.write_text(''.join(json.dumps(r) + '\n' for r in rows))
issues = sorted({r['issue'] for r in rows})
keys = {(r['grade'], r['route']) for r in rows}
print(json.dumps({'assessment_rows': len(rows), 'issues_with_rows': len(issues),
                  'distinct_series': len(keys), 'first': issues[0], 'last': issues[-1]}))
print('sample series:', sorted(keys)[:6])
