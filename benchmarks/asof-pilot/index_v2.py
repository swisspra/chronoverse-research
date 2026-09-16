"""Structure-aware index: one chunk per assessment row, plus narrative context.

Round 1 of the pilot chunked each issue into 1,400-character blocks, which cut the
price grid in half and starved every arm equally. Here each parsed assessment row
becomes its own short, self-describing chunk carrying the publication date, and the
prose is kept separately. All arms share this index, so the change is neutral between
them.
"""
import json, re, time, urllib.request
from pathlib import Path

ROOT = Path('/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot')
BASE = 'https://scgc-llmproxy.scg.com/v1'
KEY = Path('/Users/swissp/SCGC/temp.key').read_text().strip()
MODEL = 'text-embedding-3-large'
BATCH = 64
NARRATIVE_CHARS = 1200

issues = {row['id']: row for row in
          (json.loads(line) for line in (ROOT / 'pe-asia-2025.jsonl').read_text().splitlines())}
prices = [json.loads(line) for line in (ROOT / 'pe-asia-2025-prices.jsonl').read_text().splitlines()]

pieces = []
for index, price in enumerate(prices):
    grade = price['grade'].upper().strip()
    route = price['route'].upper()
    issue_id = f"pe-{price['issue']}"
    pieces.append({
        'id': f'{issue_id}#row{index:04d}', 'issue_id': issue_id, 'published': price['issue'],
        'kind': 'assessment', 'grade': grade, 'route': route,
        'text': (f"ICIS Polyethylene Asia-Pacific weekly report published {price['issue']}. "
                 f"Spot price assessment for {grade}, {route}: {price['week_price']} USD/tonne "
                 f"(week-on-week change {price['change']}). Four weeks earlier: {price['prior_price']} USD/tonne."),
    })

SKIP = re.compile(r'USD/tonne\s+(n/c|[-+]?\d)')
for issue_id, issue in issues.items():
    prose = [line.strip() for line in issue['text'].split('\n')
             if line.strip() and not SKIP.search(line) and len(line.strip()) > 40]
    blob, part = ' '.join(prose), 0
    for start in range(0, len(blob), NARRATIVE_CHARS):
        chunk = blob[start:start + NARRATIVE_CHARS].strip()
        if len(chunk) < 200:
            continue
        pieces.append({'id': f'{issue_id}#prose{part:02d}', 'issue_id': issue_id,
                       'published': issue['published'], 'kind': 'narrative',
                       'text': f"ICIS Polyethylene Asia-Pacific report published {issue['published']}. {chunk}"})
        part += 1


def embed(texts):
    body = json.dumps({'model': MODEL, 'input': texts}).encode()
    request = urllib.request.Request(f'{BASE}/embeddings', data=body, headers={
        'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.load(response)
    return ([row['embedding'] for row in sorted(payload['data'], key=lambda r: r['index'])],
            payload.get('usage', {}).get('total_tokens', 0))


kinds = {}
for piece in pieces:
    kinds[piece['kind']] = kinds.get(piece['kind'], 0) + 1
print(f'{len(pieces)} chunks {kinds}', flush=True)

vectors, tokens, started = [], 0, time.time()
for start in range(0, len(pieces), BATCH):
    got, used = embed([p['text'] for p in pieces[start:start + BATCH]])
    vectors.extend(got)
    tokens += used
with (ROOT / 'chunks-v2.jsonl').open('w') as handle:
    for piece, vector in zip(pieces, vectors, strict=True):
        handle.write(json.dumps({**piece, 'embedding': vector}) + '\n')
print(json.dumps({'chunks': len(pieces), 'by_kind': kinds, 'embedding_tokens': tokens,
                  'seconds': round(time.time() - started, 1)}))
