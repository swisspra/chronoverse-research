"""Chunk and embed the PE Asia-Pacific 2025 issues through the internal proxy only.

Every chunk keeps its issue date, which is the corpus's real knowledge clock: the
assessment for a week exists only in the issue published that week.
"""
import json, time, urllib.request
from pathlib import Path

ROOT = Path('/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot')
BASE = 'https://scgc-llmproxy.scg.com/v1'
KEY = Path('/Users/swissp/SCGC/temp.key').read_text().strip()
MODEL = 'text-embedding-3-large'
CHUNK_CHARS, OVERLAP = 1400, 200
BATCH = 32


def chunks_for(issue):
    text, out, start = issue['text'], [], 0
    while start < len(text):
        piece = text[start:start + CHUNK_CHARS].strip()
        if len(piece) > 120:
            out.append({'id': f"{issue['id']}#{len(out):03d}", 'issue_id': issue['id'],
                        'published': issue['published'], 'text': piece})
        start += CHUNK_CHARS - OVERLAP
    return out


def embed(texts):
    body = json.dumps({'model': MODEL, 'input': texts}).encode()
    req = urllib.request.Request(f'{BASE}/embeddings', data=body, headers={
        'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as response:
        payload = json.load(response)
    if payload.get('model') and MODEL not in payload['model']:
        raise RuntimeError(f"proxy served {payload['model']} instead of {MODEL}")
    return [row['embedding'] for row in sorted(payload['data'], key=lambda r: r['index'])], payload.get('usage', {})


issues = [json.loads(line) for line in (ROOT / 'pe-asia-2025.jsonl').read_text().splitlines()]
pieces = [c for issue in issues for c in chunks_for(issue)]
print(f'{len(issues)} issues -> {len(pieces)} chunks', flush=True)

vectors, tokens, started = [], 0, time.time()
for start in range(0, len(pieces), BATCH):
    batch = pieces[start:start + BATCH]
    got, usage = embed([c['text'] for c in batch])
    vectors.extend(got)
    tokens += usage.get('total_tokens', 0)
    if (start // BATCH) % 10 == 0:
        print(f'  {start + len(batch)}/{len(pieces)} chunks, {tokens} tokens', flush=True)

with (ROOT / 'chunks.jsonl').open('w') as handle:
    for piece, vector in zip(pieces, vectors, strict=True):
        handle.write(json.dumps({**piece, 'embedding': vector}) + '\n')
print(json.dumps({'chunks': len(pieces), 'embedding_tokens': tokens,
                  'seconds': round(time.time() - started, 1), 'model': MODEL}))
