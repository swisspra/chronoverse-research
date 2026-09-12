"""Corruption tests use a synthetic two-question fixture and no model inference."""
from copy import deepcopy
import hashlib
import json

import pytest

from benchmarks.verify_longmemeval_rag import (
    CUTS,
    METHODS,
    MODEL_MAX_TOKENS,
    MODEL_NAME,
    MODEL_REVISION,
    _chunk_id,
    _metrics,
    _session_key,
    _support,
    verify,
)


def source_row(question_id: str, *, abstention: bool = False):
    return {
        'question_id': question_id,
        'question': 'Where is the bag?',
        'question_date': '2024/01/02 (Tue) 12:00',
        'question_type': 'single-session-user',
        'answer': 'red',
        'answer_session_ids': ['old'],
        'haystack_session_ids': ['old', 'future'],
        'haystack_dates': ['2024/01/01 (Mon) 12:00', '2024/01/03 (Wed) 12:00'],
        'haystack_sessions': [
            [{'role': 'user', 'content': 'The bag is red.', 'has_answer': not abstention}],
            [{'role': 'user', 'content': 'The bag is blue.', 'has_answer': False}],
        ],
    }


def chunk(row, slot: int, score: float):
    turn = row['haystack_sessions'][slot][0]
    text = f"{turn['role']}: {turn['content']}"
    return {
        'text': text,
        'char_start': 0,
        'char_end': len(text),
        'model_tokens': 7,
        'id': _chunk_id(row['question_id'], slot, row['haystack_session_ids'][slot], 0, 0),
        'question_id': row['question_id'],
        'session_slot': slot,
        'session_id': row['haystack_session_ids'][slot],
        'session_date': row['haystack_dates'][slot],
        'turn_index': 0,
        'role': turn['role'],
        'part': 0,
        'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'score': score,
    }


def safe(row, value):
    return {
        'chunk_id': value['id'],
        'session_key': _session_key(row['question_id'], value['session_slot']),
        'session_date': value['session_date'],
        'role': value['role'],
        'text': value['text'],
    }


def fixture():
    rows = [source_row('q-1'), source_row('q-2_abs', abstention=True)]
    contexts = []
    diagnostics = {}
    per_query = []
    for row in rows:
        old = chunk(row, 0, 0.8)
        future = chunk(row, 1, 0.9)
        arms = {'dense': [future, old], 'dense_session_date_cutoff': [old]}
        context = {
            'question_id': row['question_id'],
            'question': row['question'],
            'question_date': row['question_date'],
            'arms': arms,
            'answerer_input': {
                'question': row['question'],
                'question_date': row['question_date'],
                'arms': {method: [safe(row, value) for value in values] for method, values in arms.items()},
            },
        }
        contexts.append(context)
        diagnostics[row['question_id']] = {
            method: {
                cut: _support(row, arms[method][: 5 if cut == 'at5' else 10])
                for cut in CUTS
            }
            for method in METHODS
        }
        per_query.append(
            {
                'question_id': row['question_id'],
                'question_type': row['question_type'],
                'methods': diagnostics[row['question_id']],
                'local_candidate_chunks': 2,
                'encoding_and_cosine_seconds': 0.1,
                'query_model_tokens': 5,
            }
        )
    raw_contexts = ('\n'.join(json.dumps(row) for row in contexts) + '\n').encode()
    raw_dataset = json.dumps(rows).encode()
    files = {'config.json': hashlib.sha256(b'config').hexdigest()}
    identity = hashlib.sha256(
        json.dumps(
            {
                'model': MODEL_NAME,
                'files': files,
                'tokens': MODEL_MAX_TOKENS,
                'dtype': 'float32',
                'pooling': 'SentenceTransformer default',
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    methods = {}
    for method in METHODS:
        methods[method] = {
            cut: _metrics([diagnostics[row['question_id']][method][cut] for row in rows])
            for cut in CUTS
        }
        methods[method]['by_ability'] = {
            'single-session-user': {
                cut: _metrics([diagnostics[row['question_id']][method][cut] for row in rows])
                for cut in CUTS
            }
        }
    result = {
        'status': 'complete',
        'paid_api_calls': 0,
        'source_sha256': hashlib.sha256(raw_dataset).hexdigest(),
        'model': {
            'name': MODEL_NAME,
            'revision': MODEL_REVISION,
            'identity': identity,
            'files': files,
            'max_tokens': MODEL_MAX_TOKENS,
            'device': 'mps',
        },
        'contexts_artifact': {
            'path': 'contexts.jsonl',
            'sha256': hashlib.sha256(raw_contexts).hexdigest(),
            'rows': 2,
        },
        'per_query': per_query,
        'methods': methods,
        'provenance': {
            'git_dirty': True,
            'git_dirty_paths': ['docs/benchmarks-longmemeval/contexts.jsonl'],
            'generated_outputs': [
                'docs/benchmarks-longmemeval/contexts.jsonl',
                'docs/benchmarks-longmemeval/results.json',
            ],
            'generated_outputs_dirty_exemption': True,
            'predictions_committed_exactly': True,
            'git_commit': 'a' * 40,
            'source_sha256': {'benchmarks/longmemeval_rag.py': '0' * 64},
        },
    }
    return raw_dataset, result, raw_contexts, contexts


def run_verify(raw_dataset, result, raw_contexts):
    return verify(
        raw_dataset,
        result,
        raw_contexts,
        expected_questions=2,
        expected_answerable=1,
        expected_abstention=1,
        model_dir=None,
        repo=None,
        enforce_official_hash=False,
    )


def encode_contexts(contexts):
    return ('\n'.join(json.dumps(row) for row in contexts) + '\n').encode()


def bind_contexts(result, contexts):
    raw = encode_contexts(contexts)
    result['contexts_artifact']['sha256'] = hashlib.sha256(raw).hexdigest()
    return raw


def test_recomputes_answerable_recall_and_excludes_abs_from_positive_metric():
    raw_dataset, result, raw_contexts, _ = fixture()
    checked = run_verify(raw_dataset, result, raw_contexts)
    assert checked['status'] == 'verified'
    assert checked['mapped_answerable_questions'] == 1
    assert checked['abstention_questions_excluded_from_positive_recall'] == 1
    assert checked['retrieval_provenance']['generated_output_dirty_exemption_validated'] is True
    for method in METHODS:
        for cut in CUTS:
            metrics = checked['methods'][method][cut]
            assert metrics['mapped_answerable_questions'] == 1
            assert metrics['mean_support_session_recall'] == 1
            assert metrics['abstention_questions'] == 1
            assert metrics['abstention_empty_context_rate'] == 0


def test_corrupt_chunk_identity_and_text_hash_are_rejected():
    raw_dataset, result, _, contexts = fixture()
    contexts[0]['arms']['dense'][0]['id'] = '0' * 64
    raw_contexts = bind_contexts(result, contexts)
    with pytest.raises(ValueError, match='identity mismatch'):
        run_verify(raw_dataset, result, raw_contexts)

    raw_dataset, result, _, contexts = fixture()
    contexts[0]['arms']['dense'][0]['text_sha256'] = '0' * 64
    raw_contexts = bind_contexts(result, contexts)
    with pytest.raises(ValueError, match='text hash mismatch'):
        run_verify(raw_dataset, result, raw_contexts)


def test_future_candidate_in_cutoff_arm_is_rejected():
    raw_dataset, result, _, contexts = fixture()
    contexts[0]['arms']['dense_session_date_cutoff'] = [contexts[0]['arms']['dense'][0]]
    contexts[0]['answerer_input']['arms']['dense_session_date_cutoff'] = [
        safe(json.loads(raw_dataset)[0], contexts[0]['arms']['dense'][0])
    ]
    raw_contexts = bind_contexts(result, contexts)
    with pytest.raises(ValueError, match='future session'):
        run_verify(raw_dataset, result, raw_contexts)


def test_aggregate_metric_corruption_is_rejected():
    raw_dataset, result, raw_contexts, _ = fixture()
    result['methods']['dense']['at5']['mean_support_session_recall'] = 0.25
    with pytest.raises(ValueError, match='aggregate methods'):
        run_verify(raw_dataset, result, raw_contexts)


def test_context_receipt_and_safe_projection_corruption_are_rejected():
    raw_dataset, result, raw_contexts, contexts = fixture()
    result['contexts_artifact']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='receipt'):
        run_verify(raw_dataset, result, raw_contexts)

    raw_dataset, result, _, contexts = fixture()
    contexts[0]['answerer_input']['arms']['dense'][0]['question_id'] = 'leak'
    raw_contexts = bind_contexts(result, contexts)
    with pytest.raises(ValueError, match='unexpected metadata'):
        run_verify(raw_dataset, result, raw_contexts)


def test_result_dataset_binding_and_model_fingerprint_are_rejected_when_corrupt():
    raw_dataset, result, raw_contexts, _ = fixture()
    result['source_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='different dataset'):
        run_verify(raw_dataset, result, raw_contexts)

    raw_dataset, result, raw_contexts, _ = fixture()
    result['model']['identity'] = '0' * 64
    with pytest.raises(ValueError, match='fingerprint'):
        run_verify(raw_dataset, result, raw_contexts)


def test_non_generated_dirty_input_is_rejected():
    raw_dataset, result, raw_contexts, _ = fixture()
    result['provenance']['git_dirty_paths'].append('benchmarks/longmemeval_rag.py')
    with pytest.raises(ValueError, match='non-generated dirty inputs'):
        run_verify(raw_dataset, result, raw_contexts)
