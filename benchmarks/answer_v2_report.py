"""Round-2 accuracy table for seven arms, using the repository's own score_answer.

The frozen summarize() hardcodes the five round-1 arms, so this aggregates with the
identical per-attempt definitions copied from it, applied to the round-2 arm set.
"""
import gzip, json, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.answer_experiment import score_answer  # noqa: E402

MANIFEST = ROOT / 'docs/benchmarks-next/answer-contexts-v2-50.jsonl'
ORDER = ('Z', 'A2', 'C2', 'B', 'D', 'D2', 'E')
LABEL = {'Z': 'no retrieval (floor)', 'A2': 'RAG hybrid lexical+dense', 'C2': 'RAG + cross-encoder',
         'B': 'long context, all versions', 'D': 'global lifecycle + post-filter',
         'D2': 'delivery projection', 'E': 'delivery + item view'}


def evaluate(state, rows, only_complete_repeats=True):
    by = {(r['query_id'], r['arm']): r for r in rows}
    expected = state.get('actual_response_model')
    done = {k: v for k, v in state['requests'].items() if v.get('status') == 'complete'}
    coverage = defaultdict(set)
    for v in done.values():
        coverage[int(v['repeat'])].add((v['query_id'], v['arm']))
    repeats = sorted(r for r, pairs in coverage.items() if len(pairs) == len(rows)) if only_complete_repeats \
        else sorted(coverage)
    acc = {arm: defaultdict(list) for arm in ORDER}
    statuses = {arm: Counter() for arm in ORDER}
    for record in state['requests'].values():
        arm, repeat = record['arm'], int(record['repeat'])
        if repeat not in repeats:
            continue
        statuses[arm][record.get('status')] += 1
        row = by[record['query_id'], arm]
        valid = (record.get('status') == 'complete' and record.get('finish_reason') == 'stop'
                 and record.get('returned_model') == expected)
        score = score_answer(record['raw_answer'], row) if valid else None
        clean = valid and not any(score[k] for k in ('citation_leak_ids', 'stale_citation_ids',
                                                     'unknown_context_citation_ids'))
        answerable = row['answerable']
        put = acc[arm]
        put['valid_completion'].append(int(valid))
        put['closed_form'].append(int(valid and score['answer_closed_form_match']))
        if answerable:
            put['support_recovery'].append(int(valid and score['equivalent_support_complete']))
            put['end_to_end'].append(int(bool(clean and score['answer_closed_form_match']
                                              and score['equivalent_support_complete'])))
            if valid:
                put['false_abstention'].append(int(score['false_abstention']))
        else:
            put['correct_abstention'].append(int(valid and score['correct_abstention']))
        if valid:
            put['stale_citation'].append(int(bool(score['stale_citation_ids'])))
    return repeats, acc, statuses, expected


def rate(values):
    return f"{100 * sum(values) / len(values):5.1f}%" if values else '   -  '


for path in sys.argv[1:]:
    raw = Path(path).read_bytes()
    state = json.loads(gzip.decompress(raw) if path.endswith('.gz') else raw)
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
    repeats, acc, statuses, model = evaluate(state, rows)
    total = sum(sum(c.values()) for c in statuses.values())
    print(f"\n=== {model} — repeats {repeats}, {total} slots ===")
    cols = [('closed_form', 'accuracy'), ('end_to_end', 'end-to-end'), ('support_recovery', 'support'),
            ('correct_abstention', 'abstain ok'), ('false_abstention', 'false abst'),
            ('stale_citation', 'stale cite'), ('valid_completion', 'valid')]
    head = f"{'arm':<4}{'system':<30}" + ''.join(f'{n:>12}' for _, n in cols)
    print(head + '\n' + '-' * len(head))
    for arm in ORDER:
        print(f"{arm:<4}{LABEL[arm]:<30}" + ''.join(f'{rate(acc[arm][k]):>12}' for k, _ in cols))
    print('denominators: accuracy/valid = all slots; support & end-to-end = answerable; '
          'abstain ok = unanswerable; false abst & stale cite = valid completions only')
