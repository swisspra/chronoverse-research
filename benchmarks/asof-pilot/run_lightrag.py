"""LightRAG 1.5.7 over the same licensed corpus and the same 100 as-of questions.

LightRAG builds its own chunks, entities and relations; it has no knowledge-time
projection, so the asked date reaches it only as words inside the question. Same
answerer model, same embedding model, same internal proxy as every other arm.

Internal proxy only. Nothing from the corpus leaves this machine or enters the repository.
"""
import asyncio, json, os, sys, time, urllib.request
from functools import partial
from pathlib import Path

import numpy as np

ROOT = Path('/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot')
BASE = 'https://scgc-llmproxy.scg.com/v1'
KEY = Path('/Users/swissp/SCGC/temp.key').read_text().strip()
EMBED_MODEL, CHAT_MODEL = 'text-embedding-3-large', 'vertex_ai/gemini-3.8-flash'
WORKDIR = ROOT / 'lightrag-store'
MODE = sys.argv[1] if len(sys.argv) > 1 else 'hybrid'

USER_PROMPT = """Rules:
- Answer with the price range exactly as the report states it, for example 1100-1150.
- If the reports do not support an answer, reply exactly: INSUFFICIENT EVIDENCE
- Answer in one short sentence."""

_usage = {'prompt': 0, 'completion': 0, 'calls': 0}


def _post(path, body, timeout=300):
    request = urllib.request.Request(f'{BASE}/{path}', data=json.dumps(body).encode(),
                                     headers={'Authorization': f'Bearer {KEY}',
                                              'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _chat(prompt, system_prompt, history, kwargs):
    messages = []
    if system_prompt:
        messages.append({'role': 'system', 'content': system_prompt})
    messages.extend(history or [])
    messages.append({'role': 'user', 'content': prompt})
    body = {'model': CHAT_MODEL, 'temperature': 0, 'max_tokens': 4096, 'messages': messages}
    if kwargs.get('response_format'):
        body['response_format'] = kwargs['response_format']
    last = None
    for attempt in range(4):
        try:
            payload = _post('chat/completions', body)
            served = payload.get('model')
            if served != CHAT_MODEL:
                raise RuntimeError(f'proxy served {served} instead of {CHAT_MODEL}')
            usage = payload.get('usage', {})
            _usage['prompt'] += usage.get('prompt_tokens', 0)
            _usage['completion'] += usage.get('completion_tokens', 0)
            _usage['calls'] += 1
            return payload['choices'][0]['message'].get('content') or ''
        except Exception as error:  # transient proxy errors only; identity errors re-raise below
            last = error
            if 'proxy served' in str(error):
                raise
            time.sleep(2 * (attempt + 1))
    raise last


async def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
    kwargs.pop('hashing_kv', None)
    return await asyncio.to_thread(_chat, prompt, system_prompt, history_messages, kwargs)


def _embed(texts):
    payload = _post('embeddings', {'model': EMBED_MODEL, 'input': list(texts)})
    rows = sorted(payload['data'], key=lambda r: r['index'])
    return np.asarray([r['embedding'] for r in rows], dtype=np.float32)


async def embedding_func(texts):
    return await asyncio.to_thread(_embed, texts)


async def main():
    from lightrag import LightRAG, QueryParam
    from lightrag.utils import EmbeddingFunc
    from lightrag.kg.shared_storage import initialize_pipeline_status

    WORKDIR.mkdir(exist_ok=True)
    rag = LightRAG(
        working_dir=str(WORKDIR),
        llm_model_func=llm_model_func,
        llm_model_name=CHAT_MODEL,
        llm_model_max_async=6,
        embedding_func=EmbeddingFunc(embedding_dim=3072, func=embedding_func),
        embedding_func_max_async=6,
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()

    seen, issues = set(), []
    for line in (ROOT / 'pe-asia-2025.jsonl').read_text().splitlines():
        issue = json.loads(line)
        if issue['id'] in seen:      # 55 files cover 51 dated issues; keep one per issue id,
            continue                 # exactly the 51 the other arms index
        seen.add(issue['id'])
        issues.append(issue)
    marker = WORKDIR / 'ingested.json'
    if not marker.exists():
        started = time.time()
        docs = [f"ICIS Polyethylene Asia-Pacific weekly report published {i['published']} "
                f"(report id {i['id']}).\n{i['text']}" for i in issues]
        await rag.ainsert(docs, ids=[i['id'] for i in issues])
        marker.write_text(json.dumps({'documents': len(docs), 'seconds': round(time.time() - started, 1),
                                      'usage': dict(_usage)}))
        print('ingested', marker.read_text(), flush=True)

    questions = [json.loads(line) for line in (ROOT / 'icis-questions.jsonl').read_text().splitlines()]
    out_path = ROOT / f'lightrag-results-{MODE}.jsonl'
    done = set()
    if out_path.exists():
        done = {json.loads(line)['question_id'] for line in out_path.read_text().splitlines()}

    started = time.time()
    with out_path.open('a') as handle:
        for index, question in enumerate(questions, 1):
            if question['id'] in done:
                continue
            before = dict(_usage)
            try:
                text = await rag.aquery(question['question'],
                                        param=QueryParam(mode=MODE, user_prompt=USER_PROMPT))
            except Exception as error:
                text = f'ERROR {error}'
            handle.write(json.dumps({'question_id': question['id'], 'arm': f'lightrag_{MODE}',
                                     'answer': text, 'finish_reason': 'stop',
                                     'usage': {'prompt_tokens': _usage['prompt'] - before['prompt'],
                                               'completion_tokens': _usage['completion'] - before['completion']},
                                     'context_ids': [], 'context_issues': []}) + '\n')
            handle.flush()
            if index % 10 == 0:
                print(f'{index}/{len(questions)} {_usage} {time.time()-started:.0f}s', flush=True)
    print(json.dumps({'mode': MODE, 'usage': _usage, 'seconds': round(time.time() - started, 1)}))
    await rag.finalize_storages()


asyncio.run(main())
