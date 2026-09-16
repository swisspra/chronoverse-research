"""Three retrieval arms over the same real ICIS corpus, same answerer, same prompt.

  static   : one index over every issue, no time awareness at all
  postfilt : retrieve from the whole index, then drop chunks published after known_at
  asof     : restrict the candidate pool to issues published by known_at, then retrieve

Internal proxy only. Nothing from the corpus leaves this machine or enters the repository.
"""
import json, re, sys, time, urllib.request
from pathlib import Path
import numpy as np

ROOT = Path('/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot')
BASE = 'https://scgc-llmproxy.scg.com/v1'
KEY = Path('/Users/swissp/SCGC/temp.key').read_text().strip()
EMBED_MODEL, CHAT_MODEL = 'text-embedding-3-large', 'vertex_ai/gemini-3.8-flash'
TOP_K = 8
ARMS = ('static', 'postfilt', 'asof')
PROMPT = """You answer strictly from the provided reports.
Question: {question}
Reports:
{context}

Rules:
- Answer with the price range exactly as the report states it, for example 1100-1150.
- If the reports do not support an answer, reply exactly: INSUFFICIENT EVIDENCE
- Answer in one short sentence, then on a new line list the report ids you used as a JSON array.
"""


def post(path, body, timeout=180):
    request = urllib.request.Request(f'{BASE}/{path}', data=json.dumps(body).encode(),
                                     headers={'Authorization': f'Bearer {KEY}',
                                              'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def embed(text):
    payload = post('embeddings', {'model': EMBED_MODEL, 'input': [text]})
    return np.asarray(payload['data'][0]['embedding'], dtype=np.float32)


def answer(question, rows):
    context = '\n'.join(f"[{r['issue_id']} published {r['published']}] {r['text']}" for r in rows)
    payload = post('chat/completions', {
        'model': CHAT_MODEL, 'temperature': 0, 'max_tokens': 4096,
        'messages': [{'role': 'user', 'content': PROMPT.format(question=question, context=context)}]})
    served = payload.get('model')
    if served != CHAT_MODEL:
        raise RuntimeError(f'proxy served {served} instead of {CHAT_MODEL}')
    choice = payload['choices'][0]
    return (choice['message'].get('content') or ''), payload.get('usage', {}), choice.get('finish_reason')


chunks = [json.loads(line) for line in (ROOT / 'chunks-v2.jsonl').read_text().splitlines()]
matrix = np.asarray([c.pop('embedding') for c in chunks], dtype=np.float32)
matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)
questions = [json.loads(line) for line in (ROOT / 'icis-questions.jsonl').read_text().splitlines()]
limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(questions)
questions = questions[:limit]

out_path = ROOT / 'arm-results-v2.jsonl'
done = set()
if out_path.exists():
    for line in out_path.read_text().splitlines():
        row = json.loads(line)
        done.add((row['question_id'], row['arm']))

started, spent = time.time(), {'prompt': 0, 'completion': 0}
with out_path.open('a') as handle:
    for index, question in enumerate(questions, 1):
        vector = embed(question['question'])
        vector /= max(float(np.linalg.norm(vector)), 1e-9)
        scores = matrix @ vector
        visible = set(question['visible_issue_ids'])
        for arm in ARMS:
            if (question['id'], arm) in done:
                continue
            order = np.argsort(-scores)
            if arm == 'static':
                picked = [chunks[i] for i in order[:TOP_K]]
            elif arm == 'postfilt':
                picked = [chunks[i] for i in order[:TOP_K] if chunks[i]['issue_id'] in visible]
            else:
                picked = [chunks[i] for i in order if chunks[i]['issue_id'] in visible][:TOP_K]
            text, usage, finish = answer(question['question'], picked) if picked else ('INSUFFICIENT EVIDENCE', {}, 'stop')
            spent['prompt'] += usage.get('prompt_tokens', 0)
            spent['completion'] += usage.get('completion_tokens', 0)
            handle.write(json.dumps({'question_id': question['id'], 'arm': arm, 'answer': text,
                                     'finish_reason': finish, 'usage': usage,
                                     'context_ids': [r['id'] for r in picked],
                                     'context_issues': sorted({r['issue_id'] for r in picked})}) + '\n')
            handle.flush()
        if index % 10 == 0:
            print(f'{index}/{len(questions)} questions, {spent} tokens, {time.time()-started:.0f}s', flush=True)
print(json.dumps({'questions': len(questions), 'arms': list(ARMS), 'tokens': spent,
                  'seconds': round(time.time() - started, 1)}))
