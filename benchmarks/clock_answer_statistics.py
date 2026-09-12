"""Offline paired statistics for the frozen FULL/VK/V/NONE clock ablation.

The query is the paired unit. Three repeats are averaged within each query and
arm before the three preregistered FULL-minus-other contrasts are computed.
This module performs no provider calls.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import statistics
from typing import Any, Mapping

from benchmarks.answer_experiment import PROMPT, score_answer
from benchmarks.answer_statistics import resource_summary, validate_binding
from benchmarks.provenance import BenchmarkRun, add_provenance_argument, sha256
from benchmarks.statistics import holm, paired_comparison


ARMS = ('FULL', 'VK', 'V', 'NONE')
COMPARATORS = ('VK', 'V', 'NONE')
REPEATS = (0, 1, 2)
SEED = 20260913
INFERENCE_METRICS = (
    'closed_form',
    'support_recovery',
    'end_to_end',
    'correct_abstention',
    'false_abstention',
)
ANSWERABLE_METRICS = {'support_recovery', 'end_to_end', 'false_abstention'}
UNANSWERABLE_METRICS = {'correct_abstention'}
SHARED_FIELDS = (
    'question',
    'recipient_id',
    'valid_at',
    'known_at',
    'received_by',
    'expected_answers',
    'gold_support_ids',
    'support_equivalence_groups',
    'visible_ids',
    'stale_ids',
    'answerable',
    'family',
    'event_only',
)


def mean(values: list[float | int]) -> float | None:
    return statistics.mean(values) if values else None


def _valid(record: Mapping[str, Any], expected_model: str) -> bool:
    return bool(
        record.get('status') == 'complete'
        and record.get('finish_reason') == 'stop'
        and record.get('returned_model') == expected_model
        and not record.get('model_guard_failure')
        and not record.get('budget_breach')
    )


def _metrics(record: Mapping[str, Any], row: Mapping[str, Any], valid: bool) -> dict[str, int | None]:
    scored = score_answer(record['raw_answer'], row) if valid else None
    answerable = bool(row['answerable'])
    clean = bool(
        valid
        and not any(
            scored[key]
            for key in ('citation_leak_ids', 'stale_citation_ids', 'unknown_context_citation_ids')
        )
    )
    return {
        'valid_completion': int(valid),
        # Missing, truncated, guarded, and wrong-model attempts are failures for
        # answer/recovery outcomes; this preserves the planned query denominator.
        'closed_form': int(bool(valid and scored['answer_closed_form_match'])),
        'support_recovery': (
            int(bool(valid and scored['equivalent_support_complete'])) if answerable else None
        ),
        'end_to_end': (
            int(bool(clean and scored['answer_closed_form_match'] and scored['equivalent_support_complete']))
            if answerable
            else None
        ),
        'correct_abstention': (
            int(bool(valid and scored['correct_abstention'])) if not answerable else None
        ),
        # Invalid attempts reveal no answer behavior, so these audits are unknown.
        'false_abstention': int(bool(scored['false_abstention'])) if valid and answerable else None,
        'strict_support_complete': (
            int(bool(valid and scored['support_complete'])) if answerable else None
        ),
        'citation_leak': int(bool(scored['citation_leak_ids'])) if valid else None,
        'stale_citation': int(bool(scored['stale_citation_ids'])) if valid else None,
        'unknown_context_citation': (
            int(bool(scored['unknown_context_citation_ids'])) if valid else None
        ),
    }


def _eligible(query: Mapping[str, Any], metric: str) -> bool:
    answerable = bool(query['answerable'])
    if metric in ANSWERABLE_METRICS:
        return answerable
    if metric in UNANSWERABLE_METRICS:
        return not answerable
    return True


def _aggregate(per_query: Mapping[str, Any], query_ids: list[str], arm: str) -> dict[str, Any]:
    metric_names = tuple(next(iter(per_query.values()))['arms'][arm][0]['metrics'])
    output = {}
    for metric in metric_names:
        values = [
            repeat['metrics'][metric]
            for query_id in query_ids
            for repeat in per_query[query_id]['arms'][arm]
            if repeat['metrics'][metric] is not None
        ]
        output[metric] = {'value': mean(values), 'denominator': len(values)}
    output['failed_fraction'] = 1 - output['valid_completion']['value']
    return output


def _contrast_family(
    per_query: Mapping[str, Any],
    rows_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    query_ids: list[str],
    metric: str,
    *,
    samples: int,
) -> dict[str, Any]:
    comparisons: dict[str, Any] = {}
    inferential_keys: list[str] = []
    for comparator in COMPARATORS:
        eligible = [qid for qid in query_ids if _eligible(rows_by_key[qid, 'FULL'], metric)]
        complete_pairs = [
            qid
            for qid in eligible
            if all(
                repeat['metrics'][metric] is not None
                for arm in ('FULL', comparator)
                for repeat in per_query[qid]['arms'][arm]
            )
        ]
        left = [
            statistics.mean(r['metrics'][metric] for r in per_query[qid]['arms']['FULL'])
            for qid in complete_pairs
        ]
        right = [
            statistics.mean(r['metrics'][metric] for r in per_query[qid]['arms'][comparator])
            for qid in complete_pairs
        ]
        key = f'FULL-{comparator}'
        if not complete_pairs or (metric == 'false_abstention' and len(complete_pairs) < 30):
            comparisons[key] = {
                'query_pairs': len(complete_pairs),
                'difference_FULL_minus_other': (
                    statistics.mean(a - b for a, b in zip(left, right, strict=True))
                    if complete_pairs
                    else None
                ),
                'eligible_query_count': len(eligible),
                'excluded_query_count': len(eligible) - len(complete_pairs),
                'inference': (
                    'Descriptive only: fewer than 30 complete query pairs.'
                    if complete_pairs
                    else 'No complete query pairs.'
                ),
            }
            continue
        result = paired_comparison(
            left,
            right,
            samples=samples,
            seed=SEED,
            family_size=len(COMPARATORS),
        )
        result['query_pairs'] = result.pop('queries')
        result['difference_FULL_minus_other'] = result.pop('mean_difference')
        result.update(
            eligible_query_count=len(eligible),
            excluded_query_count=len(eligible) - len(complete_pairs),
            pairing='query; three repeats averaged within arm before differencing',
        )
        comparisons[key] = result
        inferential_keys.append(key)

    # Planned family size stays three. Missing/descriptive tests enter Holm as p=1
    # so the remaining comparisons never receive a smaller-than-planned correction.
    planned = [comparisons[f'FULL-{arm}'].get('p_value', 1.0) for arm in COMPARATORS]
    adjusted = holm(planned)
    for comparator, adjusted_p in zip(COMPARATORS, adjusted, strict=True):
        key = f'FULL-{comparator}'
        if key in inferential_keys:
            comparisons[key]['holm_p_value'] = adjusted_p
    return {
        'family': 'three preregistered FULL-minus-other contrasts for this metric',
        'family_size': 3,
        'holm_applies_to': 'two-sided query-paired sign-permutation p-values',
        'simultaneous_intervals': (
            'Bonferroni percentile paired bootstrap, 98.333333% per contrast; '
            'distinct from Holm-adjusted p-values'
        ),
        'cross_metric_multiplicity': (
            'No study-wide correction across metrics; metric-wise claims are not jointly controlled.'
        ),
        'higher_is_better': metric != 'false_abstention',
        'comparisons': comparisons,
    }


def summarize(
    rows: list[Mapping[str, Any]],
    records: Mapping[str, Mapping[str, Any]],
    expected_model: str,
    *,
    expected_queries: int = 50,
    samples: int = 10_000,
) -> dict[str, Any]:
    rows_by_key = {(str(row['query_id']), str(row['arm'])): row for row in rows}
    if len(rows_by_key) != len(rows):
        raise ValueError('Duplicate clock manifest query/arm.')
    query_ids = sorted({key[0] for key in rows_by_key})
    if len(query_ids) != expected_queries:
        raise ValueError(f'Expected exactly {expected_queries} frozen clock queries.')
    if any((query_id, arm) not in rows_by_key for query_id in query_ids for arm in ARMS):
        raise ValueError('Every query requires exactly FULL, VK, V, and NONE rows.')
    if {key[1] for key in rows_by_key} != set(ARMS):
        raise ValueError('Unexpected clock arm.')
    for query_id in query_ids:
        reference = rows_by_key[query_id, 'FULL']
        if any(
            rows_by_key[query_id, arm].get(field) != reference.get(field)
            for arm in ARMS
            for field in SHARED_FIELDS
        ):
            raise ValueError('Shared scoring/query metadata differs across clock arms.')

    indexed: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    for record in records.values():
        key = (str(record['query_id']), str(record['arm']), int(record['repeat']))
        if key in indexed or key[:2] not in rows_by_key or key[2] not in REPEATS:
            raise ValueError('Unexpected or duplicate recorded clock dispatch slot.')
        indexed[key] = record

    per_query: dict[str, Any] = {}
    statuses = {arm: Counter() for arm in ARMS}
    actual_models = Counter()
    resources = {arm: {'records': [], 'completed': [], 'answered': []} for arm in ARMS}
    for query_id in query_ids:
        per_query[query_id] = {
            'family': rows_by_key[query_id, 'FULL']['family'],
            'answerable': bool(rows_by_key[query_id, 'FULL']['answerable']),
            'arms': {},
        }
        for arm in ARMS:
            row = rows_by_key[query_id, arm]
            repeats = []
            for repeat in REPEATS:
                record = indexed.get((query_id, arm, repeat), {})
                status = str(record.get('status', 'missing'))
                statuses[arm][status] += 1
                valid = _valid(record, expected_model)
                if record:
                    resources[arm]['records'].append(record)
                    actual_models[str(record.get('returned_model', 'unknown'))] += 1
                scored = score_answer(record['raw_answer'], row) if valid else None
                if valid:
                    resources[arm]['completed'].append(record)
                    if not scored['abstained']:
                        resources[arm]['answered'].append(record)
                repeats.append(
                    {
                        'repeat': repeat,
                        'status': status,
                        'metrics': _metrics(record, row, valid),
                        'seconds': record.get('seconds'),
                    }
                )
            per_query[query_id]['arms'][arm] = repeats

    arm_summaries = {
        arm: {
            'metrics': _aggregate(per_query, query_ids, arm),
            'statuses': dict(statuses[arm]),
            'resources': resource_summary(**resources[arm]),
        }
        for arm in ARMS
    }
    contrasts = {
        metric: _contrast_family(
            per_query,
            rows_by_key,
            query_ids,
            metric,
            samples=samples,
        )
        for metric in INFERENCE_METRICS
    }
    return {
        'planned_queries': len(query_ids),
        'planned_requests': len(rows) * len(REPEATS),
        'recorded_requests': len(records),
        'expected_response_model': expected_model,
        'actual_response_models': dict(actual_models),
        'arms': arm_summaries,
        'paired_contrasts': contrasts,
        'per_query': per_query,
        'missing_and_truncation_policy': {
            'answer_and_recovery_metrics': 'score 0 and retain the planned query denominator',
            'citation_and_false_abstention_audits': 'unknown; exclude only from that audit',
            'invalid_statuses': (
                'missing, non-stop, wrong-model, model-guard failure, and budget breach'
            ),
            'attempt_costs': 'all recorded attempts remain in resource summaries',
        },
        'limitations': [
            'The fixed synthetic 50-query pool is not a public benchmark sample.',
            'The query is the paired unit; three repeats are not independent observations.',
            'Complete-pair exclusion for false abstention can be biased and is descriptive below 30 pairs.',
            'Literal closed-form matching is not semantic answer evaluation.',
            'Three contrasts are corrected within each metric, not jointly across metrics.',
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--expected-response-model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prompt', type=Path, default=PROMPT)
    parser.add_argument('--captured-input-hashes', type=Path)
    add_provenance_argument(parser)
    args = parser.parse_args()
    run = BenchmarkRun(allow_dirty=args.allow_dirty)
    inputs = {path: sha256(path) for path in (args.manifest, args.results, args.prompt)}
    if args.captured_input_hashes:
        inputs[args.captured_input_hashes] = sha256(args.captured_input_hashes)
    raw_file = args.manifest.read_bytes()
    raw = gzip.decompress(raw_file) if args.manifest.suffix == '.gz' else raw_file
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    result = json.loads(args.results.read_text())
    captured = (
        json.loads(args.captured_input_hashes.read_text()) if args.captured_input_hashes else None
    )
    binding = validate_binding(raw, rows, result, args.prompt.read_bytes(), captured)
    summary = summarize(rows, result['requests'], args.expected_response_model)
    if any(sha256(path) != value for path, value in inputs.items()):
        raise RuntimeError('Clock statistics input changed during aggregation.')
    run.write_json(
        args.output,
        {
            'status': (
                'complete attempt inventory'
                if summary['recorded_requests'] == summary['planned_requests']
                else 'partial attempts retained'
            ),
            'manifest_file_sha256': inputs[args.manifest],
            'result_file_sha256': inputs[args.results],
            'manifest_binding': binding,
            'captured_hash_export_sha256': inputs.get(args.captured_input_hashes),
            **summary,
        },
    )


if __name__ == '__main__':
    main()
