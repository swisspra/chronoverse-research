"""Independently verify saved LongMemEval-S retrieval artifacts; no model calls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Mapping

from benchmarks.provenance import BenchmarkRun, add_provenance_argument, sha256


ROOT = Path(__file__).resolve().parents[1]
DATA_SHA256 = 'd6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442'
MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'
MODEL_REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
MODEL_MAX_TOKENS = 256
MODEL_DIR = (
    ROOT
    / '.model-cache/mps/models--sentence-transformers--all-MiniLM-L6-v2/snapshots'
    / MODEL_REVISION
)
METHODS = ('dense', 'dense_session_date_cutoff')
CUTS = ('at5', 'at10')
DIAGNOSTIC_NOTE = (
    'Session-level coverage does not establish that a selected chunk contains the answer. '
    'Retained _abs session IDs are excluded from positive support metrics.'
)


def _hash_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _clock(value: str) -> datetime:
    return datetime.strptime(value, '%Y/%m/%d (%a) %H:%M')


def _chunk_id(question_id: str, slot: int, session_id: str, turn: int, part: int) -> str:
    identity = json.dumps(
        [question_id, slot, session_id, turn, part],
        separators=(',', ':'),
    )
    return _hash_bytes(identity.encode())


def _session_key(question_id: str, slot: int) -> str:
    return _hash_bytes(json.dumps([question_id, slot]).encode())


def _split_text(text: str, tokenizer: Any) -> list[dict[str, Any]]:
    """Independently reconstruct the frozen lossless <=256-token split."""

    budget = MODEL_MAX_TOKENS - tokenizer.num_special_tokens_to_add(pair=False)
    if budget < 1:
        raise ValueError('Tokenizer special tokens exceed the frozen chunk budget')
    offsets = tokenizer(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
    )['offset_mapping']
    if not offsets:
        return []
    chunks = []
    start_token = 0
    start_char = 0
    while start_token < len(offsets):
        end_token = min(start_token + budget, len(offsets))
        while end_token > start_token:
            end_char = offsets[end_token][0] if end_token < len(offsets) else len(text)
            piece = text[start_char:end_char]
            length = len(
                tokenizer(piece, add_special_tokens=True, truncation=False)['input_ids']
            )
            if length <= MODEL_MAX_TOKENS:
                break
            end_token -= 1
        if end_token == start_token:
            raise ValueError('Tokenizer cannot reconstruct one frozen chunk')
        chunks.append(
            {
                'text': piece,
                'char_start': start_char,
                'char_end': end_char,
                'model_tokens': length,
            }
        )
        start_token = end_token
        start_char = end_char
    if ''.join(chunk['text'] for chunk in chunks) != text:
        raise ValueError('Independent tokenizer reconstruction dropped source text')
    return chunks


def _build_ledger(row: Mapping[str, Any], tokenizer: Any) -> list[dict[str, Any]]:
    ledger = []
    question_id = str(row['question_id'])
    for slot, (session_id, session_date, turns) in enumerate(
        zip(
            row['haystack_session_ids'],
            row['haystack_dates'],
            row['haystack_sessions'],
            strict=True,
        )
    ):
        for turn_index, turn in enumerate(turns):
            text = f"{turn['role']}: {turn['content']}"
            for part, chunk in enumerate(_split_text(text, tokenizer)):
                ledger.append(
                    {
                        **chunk,
                        'id': _chunk_id(question_id, slot, session_id, turn_index, part),
                        'question_id': question_id,
                        'session_slot': slot,
                        'session_id': session_id,
                        'session_date': session_date,
                        'turn_index': turn_index,
                        'role': turn['role'],
                        'part': part,
                        'text_sha256': _hash_bytes(chunk['text'].encode()),
                    }
                )
    return ledger


def _assert_equal(actual: Any, expected: Any, label: str) -> None:
    if isinstance(expected, float):
        if not isinstance(actual, (int, float)) or not math.isclose(
            float(actual), expected, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(f'{label} differs from independently recomputed value')
        return
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise ValueError(f'{label} keys differ from independently recomputed value')
        for key, value in expected.items():
            _assert_equal(actual[key], value, f'{label}.{key}')
        return
    if actual != expected:
        raise ValueError(f'{label} differs from independently recomputed value')


def _support(row: Mapping[str, Any], selected: list[Mapping[str, Any]]) -> dict[str, Any]:
    gold = set(row['answer_session_ids'])
    available = set(row['haystack_session_ids'])
    found = {chunk['session_id'] for chunk in selected} & gold
    abstention = str(row['question_id']).endswith('_abs')
    mapped = gold <= available
    eligible = bool(gold) and mapped and not abstention
    return {
        'official_answer_session_ids': sorted(gold),
        'unmapped_answer_session_ids': sorted(gold - available),
        'qrel_coverage_complete': mapped,
        'support_sessions_returned': len(found),
        'support_session_recall': len(found) / len(gold) if eligible else None,
        'complete_support_sessions': gold <= {c['session_id'] for c in selected} if eligible else None,
        'abstention_question': abstention,
        'empty_context': not selected,
        'diagnostic_note': DIAGNOSTIC_NOTE,
    }


def _metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in rows if row['support_session_recall'] is not None]
    abstentions = [row for row in rows if row['abstention_question']]
    return {
        'questions': len(rows),
        'mapped_answerable_questions': len(answerable),
        'mean_support_session_recall': (
            sum(row['support_session_recall'] for row in answerable) / len(answerable)
            if answerable
            else None
        ),
        'complete_support_sessions_rate': (
            sum(row['complete_support_sessions'] for row in answerable) / len(answerable)
            if answerable
            else None
        ),
        'abstention_questions': len(abstentions),
        'abstention_empty_context_rate': (
            sum(row['empty_context'] for row in abstentions) / len(abstentions)
            if abstentions
            else None
        ),
        'unmapped_questions': sum(not row['qrel_coverage_complete'] for row in rows),
    }


def _verify_chunk(
    row: Mapping[str, Any],
    chunk: Mapping[str, Any],
    *,
    cutoff: bool,
    reconstructed: Mapping[str, Mapping[str, Any]] | None,
) -> None:
    required = {
        'text',
        'char_start',
        'char_end',
        'model_tokens',
        'id',
        'question_id',
        'session_slot',
        'session_id',
        'session_date',
        'turn_index',
        'role',
        'part',
        'text_sha256',
        'score',
    }
    if set(chunk) != required:
        raise ValueError('Selected chunk fields differ from the frozen ledger schema')
    question_id = str(row['question_id'])
    if chunk['question_id'] != question_id:
        raise ValueError('Cross-question selected candidate')
    slot = chunk['session_slot']
    turn_index = chunk['turn_index']
    part = chunk['part']
    if not all(isinstance(value, int) and value >= 0 for value in (slot, turn_index, part)):
        raise ValueError('Invalid ledger slot, turn, or part')
    try:
        session_id = row['haystack_session_ids'][slot]
        session_date = row['haystack_dates'][slot]
        turn = row['haystack_sessions'][slot][turn_index]
    except (IndexError, TypeError):
        raise ValueError('Selected candidate points outside its question ledger') from None
    if chunk['session_id'] != session_id or chunk['session_date'] != session_date:
        raise ValueError('Selected candidate session metadata differs from its ledger slot')
    if chunk['role'] != turn['role']:
        raise ValueError('Selected candidate role differs from its source turn')
    source = f"{turn['role']}: {turn['content']}"
    start, end = chunk['char_start'], chunk['char_end']
    if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(source)):
        raise ValueError('Selected candidate has invalid source offsets')
    if chunk['text'] != source[start:end]:
        raise ValueError('Selected candidate text differs from source offsets')
    if chunk['text_sha256'] != _hash_bytes(chunk['text'].encode()):
        raise ValueError('Selected candidate text hash mismatch')
    if chunk['id'] != _chunk_id(question_id, slot, session_id, turn_index, part):
        raise ValueError('Selected candidate identity mismatch')
    if not isinstance(chunk['model_tokens'], int) or not 0 < chunk['model_tokens'] <= MODEL_MAX_TOKENS:
        raise ValueError('Selected candidate violates the frozen model-token bound')
    if not isinstance(chunk['score'], (int, float)) or not math.isfinite(chunk['score']):
        raise ValueError('Selected candidate score is not finite')
    if cutoff and _clock(session_date) > _clock(row['question_date']):
        raise ValueError('Date-cutoff arm contains a future session')
    if reconstructed is not None:
        expected = reconstructed.get(chunk['id'])
        if expected is None:
            raise ValueError('Selected candidate is absent from the reconstructed ledger')
        if {key: value for key, value in chunk.items() if key != 'score'} != expected:
            raise ValueError('Selected candidate differs from the independently reconstructed ledger')


def _verify_context_row(
    row: Mapping[str, Any],
    context: Mapping[str, Any],
    reconstructed: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if set(context) != {'question_id', 'question', 'question_date', 'arms', 'answerer_input'}:
        raise ValueError('Context row schema differs from the frozen runner')
    if any(context[key] != row[key] for key in ('question_id', 'question', 'question_date')):
        raise ValueError('Context row does not match its official question')
    if set(context['arms']) != set(METHODS):
        raise ValueError('Context row does not contain exactly the two frozen methods')
    seen: dict[str, Mapping[str, Any]] = {}
    for method in METHODS:
        selected = context['arms'][method]
        if not isinstance(selected, list) or len(selected) > 10:
            raise ValueError('A retrieval arm must contain at most ten chunks')
        if len({chunk['id'] for chunk in selected}) != len(selected):
            raise ValueError('Duplicate selected chunk identity within an arm')
        for chunk in selected:
            _verify_chunk(
                row,
                chunk,
                cutoff=method == 'dense_session_date_cutoff',
                reconstructed=reconstructed,
            )
            previous = seen.get(chunk['id'])
            if previous is not None and previous != chunk:
                raise ValueError('Same chunk identity has conflicting metadata across arms')
            seen[chunk['id']] = chunk
        expected_order = sorted(selected, key=lambda chunk: (-chunk['score'], chunk['id']))
        if selected != expected_order:
            raise ValueError('Selected chunks violate deterministic score/ID ordering')

    answerer = context['answerer_input']
    if set(answerer) != {'question', 'question_date', 'arms'}:
        raise ValueError('Answerer input exposes fields outside the frozen safe schema')
    if answerer['question'] != row['question'] or answerer['question_date'] != row['question_date']:
        raise ValueError('Answerer input question/date mismatch')
    if set(answerer['arms']) != set(METHODS):
        raise ValueError('Answerer input methods differ from audit methods')
    safe_keys = {'chunk_id', 'session_key', 'session_date', 'role', 'text'}
    for method in METHODS:
        audit = context['arms'][method]
        safe = answerer['arms'][method]
        if len(audit) != len(safe):
            raise ValueError('Answerer input length differs from its audit arm')
        for chunk, unit in zip(audit, safe, strict=True):
            if set(unit) != safe_keys:
                raise ValueError('Answerer input unit exposes unexpected metadata')
            expected = {
                'chunk_id': chunk['id'],
                'session_key': _session_key(str(row['question_id']), chunk['session_slot']),
                'session_date': chunk['session_date'],
                'role': chunk['role'],
                'text': chunk['text'],
            }
            if unit != expected:
                raise ValueError('Answerer input does not exactly project its audit chunk')
    return {
        method: {
            cut: _support(row, context['arms'][method][: 5 if cut == 'at5' else 10])
            for cut in CUTS
        }
        for method in METHODS
    }


def _verify_model(result: Mapping[str, Any], model_dir: Path | None) -> dict[str, Any]:
    model = result['model']
    if (
        model.get('name') != MODEL_NAME
        or model.get('revision') != MODEL_REVISION
        or model.get('max_tokens') != MODEL_MAX_TOKENS
        or model.get('device') != 'mps'
    ):
        raise ValueError('Saved model identity differs from the frozen protocol')
    files = model.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Saved model artifact hashes are missing')
    identity = _hash_bytes(
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
    )
    if model.get('identity') != identity:
        raise ValueError('Saved model fingerprint is not reconstructible from its artifact hashes')
    local_verified = False
    if model_dir is not None:
        actual = {
            path.relative_to(model_dir).as_posix(): sha256(path)
            for path in sorted(model_dir.rglob('*'))
            if path.is_file()
        }
        if actual != files:
            raise ValueError('Local frozen model files differ from the saved artifact hashes')
        local_verified = True
    return {'identity': identity, 'files': len(files), 'local_files_verified': local_verified}


def _verify_provenance(result: Mapping[str, Any], repo: Path | None) -> dict[str, Any]:
    provenance = result.get('provenance')
    if not isinstance(provenance, dict):
        raise ValueError('Result provenance is missing')
    dirty_paths = set(provenance.get('git_dirty_paths') or [])
    generated = set(provenance.get('generated_outputs') or [])
    generated_only = bool(
        provenance.get('generated_outputs_dirty_exemption')
        and dirty_paths
        and dirty_paths <= generated
    )
    if provenance.get('git_dirty') is not False and not generated_only:
        raise ValueError('Retrieval result has non-generated dirty inputs')
    if provenance.get('predictions_committed_exactly') is not True:
        raise ValueError('Retrieval result does not bind the committed predictions')
    commit = provenance.get('git_commit')
    sources = provenance.get('source_sha256')
    if not isinstance(commit, str) or not isinstance(sources, dict) or not sources:
        raise ValueError('Result source provenance is incomplete')
    verified = 0
    if repo is not None:
        for relative, expected in sources.items():
            if relative.startswith('<EXTERNAL>/'):
                continue
            try:
                raw = subprocess.check_output(
                    ['git', '-C', str(repo), 'show', f'{commit}:{relative}'],
                    stderr=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError:
                raise ValueError(f'Cannot reconstruct committed source: {relative}') from None
            if _hash_bytes(raw) != expected:
                raise ValueError(f'Committed source hash mismatch: {relative}')
            verified += 1
    return {
        'git_commit': commit,
        'source_hashes': len(sources),
        'committed_sources_verified': verified,
        'generated_output_dirty_exemption_validated': generated_only,
    }


def _cutoff_gold_diagnosis(
    rows: list[Mapping[str, Any]], abstention_ids: set[str]
) -> dict[str, Any]:
    affected_questions = set()
    affected_by_ability = Counter()
    sessions_by_ability = Counter()
    same_day_later = 0
    later_calendar_date = 0
    seen = set()
    for row in rows:
        question_id = str(row['question_id'])
        if question_id in abstention_ids:
            continue
        question_time = _clock(row['question_date'])
        gold = set(row['answer_session_ids'])
        for session_id, session_date in zip(
            row['haystack_session_ids'], row['haystack_dates'], strict=True
        ):
            identity = (question_id, session_id)
            if session_id not in gold or identity in seen:
                continue
            seen.add(identity)
            session_time = _clock(session_date)
            if session_time <= question_time:
                continue
            affected_questions.add(question_id)
            ability = str(row['question_type'])
            sessions_by_ability[ability] += 1
            if session_time.date() == question_time.date():
                same_day_later += 1
            else:
                later_calendar_date += 1
    for row in rows:
        if str(row['question_id']) in affected_questions:
            affected_by_ability[str(row['question_type'])] += 1
    return {
        'answerable_questions_with_gold_after_cutoff': len(affected_questions),
        'gold_session_ids_after_cutoff': sum(sessions_by_ability.values()),
        'same_calendar_day_but_later_time': same_day_later,
        'strictly_later_calendar_date': later_calendar_date,
        'affected_questions_by_ability': dict(sorted(affected_by_ability.items())),
        'excluded_gold_session_ids_by_ability': dict(sorted(sessions_by_ability.items())),
        'interpretation': (
            'Direct supplied-timestamp inventory only; it explains unreachable qrels under the cutoff '
            'but does not measure ranking quality or justify changing the frozen rule.'
        ),
    }


def verify(
    dataset_raw: bytes,
    result: Mapping[str, Any],
    contexts_raw: bytes,
    *,
    expected_questions: int = 500,
    expected_answerable: int = 470,
    expected_abstention: int = 30,
    model_dir: Path | None = MODEL_DIR,
    repo: Path | None = ROOT,
    tokenizer: Any = None,
    enforce_official_hash: bool = True,
) -> dict[str, Any]:
    source_hash = _hash_bytes(dataset_raw)
    if enforce_official_hash and source_hash != DATA_SHA256:
        raise ValueError('Dataset differs from frozen LongMemEval-S source')
    rows = json.loads(dataset_raw)
    by_id = {str(row['question_id']): row for row in rows}
    if len(rows) != expected_questions or len(by_id) != expected_questions:
        raise ValueError('Official dataset question count or identities differ')
    abstention_ids = {qid for qid in by_id if qid.endswith('_abs')}
    if len(abstention_ids) != expected_abstention:
        raise ValueError('Official abstention count differs from the frozen protocol')
    if any(
        not by_id[qid]['answer_session_ids']
        or not set(by_id[qid]['answer_session_ids']) <= set(by_id[qid]['haystack_session_ids'])
        for qid in abstention_ids
    ):
        raise ValueError('Official abstention rows must retain mapped related session IDs')
    answerable_ids = {
        qid
        for qid, row in by_id.items()
        if qid not in abstention_ids
        and bool(row['answer_session_ids'])
        and set(row['answer_session_ids']) <= set(row['haystack_session_ids'])
    }
    if len(answerable_ids) != expected_answerable:
        raise ValueError('Mapped answerable count differs from the frozen protocol')
    if result.get('status') != 'complete' or result.get('paid_api_calls') != 0:
        raise ValueError('A complete zero-provider retrieval result is required')
    if result.get('source_sha256') != source_hash:
        raise ValueError('Result is bound to a different dataset hash')

    if not contexts_raw.endswith(b'\n'):
        raise ValueError('Context JSONL lacks its final newline')
    context_lines = contexts_raw.decode().splitlines()
    if any(not line for line in context_lines):
        raise ValueError('Context JSONL contains an empty record')
    context_rows = [json.loads(line) for line in context_lines]
    contexts_by_id = {str(row['question_id']): row for row in context_rows}
    if len(context_rows) != expected_questions or set(contexts_by_id) != set(by_id):
        raise ValueError('Context JSONL question identities/count differ from the dataset')
    context_receipt = result.get('contexts_artifact', {})
    if (
        context_receipt.get('sha256') != _hash_bytes(contexts_raw)
        or context_receipt.get('rows') != expected_questions
        or context_receipt.get('path') != 'contexts.jsonl'
    ):
        raise ValueError('Context artifact receipt does not match exact JSONL bytes')

    per_query = result.get('per_query')
    if not isinstance(per_query, list):
        raise ValueError('Per-query retrieval records are missing')
    result_by_id = {str(row['question_id']): row for row in per_query}
    if len(per_query) != expected_questions or set(result_by_id) != set(by_id):
        raise ValueError('Result per-query identities/count differ from the dataset')

    recomputed: dict[str, dict[str, dict[str, Any]]] = {}
    selected_counts = Counter()
    reconstructed_inventory = Counter()
    unique_chunk_texts = set()
    for question_id, row in by_id.items():
        context = contexts_by_id[question_id]
        reconstructed = None
        query_tokens = None
        if tokenizer is not None:
            ledger = _build_ledger(row, tokenizer)
            reconstructed = {chunk['id']: chunk for chunk in ledger}
            if len(reconstructed) != len(ledger):
                raise ValueError('Independent ledger reconstruction produced duplicate chunk IDs')
            query_tokens = len(tokenizer(row['question'], truncation=False)['input_ids'])
            reconstructed_inventory['questions'] += 1
            reconstructed_inventory['session_instances'] += len(row['haystack_sessions'])
            reconstructed_inventory['turns'] += sum(
                len(turns) for turns in row['haystack_sessions']
            )
            reconstructed_inventory['chunks'] += len(ledger)
            reconstructed_inventory['model_tokens_with_specials'] += sum(
                chunk['model_tokens'] for chunk in ledger
            )
            reconstructed_inventory['split_turns'] += sum(chunk['part'] == 1 for chunk in ledger)
            reconstructed_inventory['future_session_instances'] += sum(
                _clock(date) > _clock(row['question_date']) for date in row['haystack_dates']
            )
            reconstructed_inventory['duplicate_session_id_ledgers'] += len(
                row['haystack_session_ids']
            ) != len(set(row['haystack_session_ids']))
            reconstructed_inventory['queries_exceeding_256_tokens'] += (
                query_tokens > MODEL_MAX_TOKENS
            )
            unique_chunk_texts.update(chunk['text_sha256'] for chunk in ledger)
        diagnostics = _verify_context_row(row, context, reconstructed)
        record = result_by_id[question_id]
        expected_record_fields = {
            'question_id',
            'question_type',
            'methods',
            'local_candidate_chunks',
            'encoding_and_cosine_seconds',
            'query_model_tokens',
        }
        if set(record) != expected_record_fields:
            raise ValueError('Per-query result schema differs from the frozen runner')
        if set(record['methods']) != set(METHODS) or any(
            set(record['methods'][method]) != set(CUTS) for method in METHODS
        ):
            raise ValueError('Per-query diagnostic methods/cuts differ from the frozen runner')
        if record.get('question_type') != row['question_type']:
            raise ValueError('Per-query ability label differs from the official dataset')
        if record.get('local_candidate_chunks', 0) < max(
            len(context['arms'][method]) for method in METHODS
        ):
            raise ValueError('Selected count exceeds the recorded local candidate ledger')
        if reconstructed is not None and record['local_candidate_chunks'] != len(reconstructed):
            raise ValueError('Recorded candidate count differs from reconstructed question ledger')
        elapsed = record.get('encoding_and_cosine_seconds')
        if not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError('Per-query retrieval time is invalid')
        if not isinstance(record.get('query_model_tokens'), int) or record['query_model_tokens'] <= 0:
            raise ValueError('Per-query model-token count is invalid')
        if query_tokens is not None and record['query_model_tokens'] != query_tokens:
            raise ValueError('Recorded query token count differs from tokenizer reconstruction')
        for method in METHODS:
            selected_counts[f'{method}_at10'] += len(context['arms'][method])
            for cut in CUTS:
                _assert_equal(
                    record['methods'][method][cut],
                    diagnostics[method][cut],
                    f'{question_id}.{method}.{cut}',
                )
        recomputed[question_id] = diagnostics

    expected_methods: dict[str, Any] = {}
    abilities = sorted({str(row['question_type']) for row in rows})
    for method in METHODS:
        expected_methods[method] = {
            cut: _metrics([recomputed[qid][method][cut] for qid in by_id]) for cut in CUTS
        }
        expected_methods[method]['by_ability'] = {
            ability: {
                cut: _metrics(
                    [
                        recomputed[qid][method][cut]
                        for qid, row in by_id.items()
                        if row['question_type'] == ability
                    ]
                )
                for cut in CUTS
            }
            for ability in abilities
        }
    _assert_equal(result.get('methods'), expected_methods, 'aggregate methods')

    if tokenizer is not None:
        _assert_equal(result.get('inventory'), dict(reconstructed_inventory), 'runner inventory')
        if result.get('unique_exact_chunk_texts') != len(unique_chunk_texts):
            raise ValueError('Unique exact chunk count differs from reconstruction')

    empty_context = {
        method: {
            cut: {
                'all_questions': sum(
                    recomputed[qid][method][cut]['empty_context'] for qid in by_id
                ),
                'mapped_answerable': sum(
                    recomputed[qid][method][cut]['empty_context'] for qid in answerable_ids
                ),
                'abstention': sum(
                    recomputed[qid][method][cut]['empty_context'] for qid in abstention_ids
                ),
            }
            for cut in CUTS
        }
        for method in METHODS
    }

    model_check = _verify_model(result, model_dir)
    provenance_check = _verify_provenance(result, repo)
    return {
        'status': 'verified',
        'dataset_sha256': source_hash,
        'contexts_sha256': _hash_bytes(contexts_raw),
        'questions': expected_questions,
        'mapped_answerable_questions': len(answerable_ids),
        'abstention_questions_excluded_from_positive_recall': len(abstention_ids),
        'methods': expected_methods,
        'empty_context_counts': empty_context,
        'cutoff_gold_diagnosis': _cutoff_gold_diagnosis(rows, abstention_ids),
        'selected_context_counts': dict(selected_counts),
        'ledger_reconstruction': {
            'tokenizer_loaded_without_model_inference': tokenizer is not None,
            'inventory': dict(reconstructed_inventory) if tokenizer is not None else None,
            'unique_exact_chunk_texts': len(unique_chunk_texts) if tokenizer is not None else None,
        },
        'model': model_check,
        'retrieval_provenance': provenance_check,
        'checks': [
            'exact dataset/context hashes and complete question identities',
            'independent session recall@5/@10 and empty-context recomputation',
            'question-scoped chunk identity, source offsets, text hash, and deterministic order',
            'inclusive session-date cutoff and safe answerer projection',
            'model fingerprint/files and committed clean-run source hashes',
        ],
        'not_verified_without_model_inference': (
            'Cosine values and whether saved chunks are globally top-ranked within each full ledger; '
            'selected identities, text, cutoff, ordering, and reported metrics are verified.'
        ),
        'paid_api_calls': 0,
    }


def _read(path: Path) -> bytes:
    raw = path.read_bytes()
    return gzip.decompress(raw) if path.suffix == '.gz' else raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT / '.benchmark-data/longmemeval-s.json')
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--contexts', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path, default=MODEL_DIR)
    parser.add_argument('--output', type=Path)
    add_provenance_argument(parser)
    args = parser.parse_args()
    run = BenchmarkRun(allow_dirty=args.allow_dirty) if args.output else None
    initial = {path: sha256(path) for path in (args.dataset, args.results, args.contexts)}
    dataset_raw, result_raw, contexts_raw = map(
        _read,
        (args.dataset, args.results, args.contexts),
    )
    result = json.loads(result_raw)
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        str(args.model_dir),
        local_files_only=True,
        use_fast=True,
    )
    verified = verify(
        dataset_raw,
        result,
        contexts_raw,
        model_dir=args.model_dir,
        tokenizer=tokenizer,
    )
    if any(sha256(path) != digest for path, digest in initial.items()):
        raise RuntimeError('LongMemEval verification input changed during the audit')
    payload = {
        **verified,
        'input_file_sha256': {str(path.name): digest for path, digest in initial.items()},
    }
    if run is not None:
        run.write_json(args.output, payload)
    else:
        print(json.dumps(payload, sort_keys=True))


if __name__ == '__main__':
    main()
