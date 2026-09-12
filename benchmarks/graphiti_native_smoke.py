"""Guarded two-episode native Graphiti smoke; never runs without an explicit flag."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from benchmarks.graphiti_native_preflight import (
    GRAPHITI_COMMIT,
    GRAPHITI_VERSION,
    build_native_graphiti,
    group_id,
)
from benchmarks.provenance import BenchmarkRun, add_provenance_argument


ROOT = Path(__file__).resolve().parents[1]
SMOKE_QUESTION_ID = 'wi14-native-graphiti-smoke-v1'
SMOKE_QUERY = 'What tea does the user prefer now?'


class BudgetExceeded(RuntimeError):
    """A request was blocked before network dispatch by the frozen reservation."""


REQUEST_FRAMING_ALLOWANCE_BYTES = 1024


@dataclass(frozen=True)
class Reservation:
    max_chat_requests: int = 24
    max_embedding_requests: int = 64
    max_input_token_upper_bound: int = 500_000
    max_output_token_ceiling: int = 98_304


def _request_input_bytes(kwargs: Mapping[str, Any]) -> int:
    """Conservative token ceiling over the complete serialized SDK request."""

    serialized = json.dumps(
        kwargs,
        ensure_ascii=False,
        separators=(',', ':'),
        default=lambda value: f'<{type(value).__module__}.{type(value).__qualname__}>',
    ).encode()
    # One UTF-8 byte per token is deliberately conservative for BPE tokenizers.
    # The fixed allowance covers provider framing that is absent from SDK kwargs.
    return len(serialized) + REQUEST_FRAMING_ALLOWANCE_BYTES


def _usage(response: Any) -> dict[str, int | None]:
    usage = getattr(response, 'usage', None)
    if usage is None:
        return {
            'input_tokens': None,
            'output_tokens': None,
            'total_tokens': None,
        }
    input_tokens = getattr(usage, 'prompt_tokens', None)
    if input_tokens is None:
        input_tokens = getattr(usage, 'input_tokens', None)
    output_tokens = getattr(usage, 'completion_tokens', None)
    if output_tokens is None:
        output_tokens = getattr(usage, 'output_tokens', None)
    return {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'total_tokens': getattr(usage, 'total_tokens', None),
    }


class UsageLedger:
    """Reserve before dispatch and checkpoint usage without prompts or secrets."""

    def __init__(self, limits: Reservation, checkpoint: Path):
        self.limits = limits
        self.checkpoint = checkpoint
        self.events: list[dict[str, Any]] = []
        self.chat_requests = 0
        self.embedding_requests = 0
        self.input_reserved = 0
        self.output_reserved = 0
        self._lock_path = checkpoint.with_suffix(checkpoint.suffix + '.lock')
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = self._lock_path.open('a+')
        try:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock_file.close()
            raise RuntimeError('another native smoke owns the usage ledger') from None
        if checkpoint.exists():
            self.close()
            raise RuntimeError(
                'native smoke usage ledger already exists; archive it before a new isolated run'
            )

    def close(self) -> None:
        lock_file = getattr(self, '_lock_file', None)
        if lock_file is not None and not lock_file.closed:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def _write(self) -> None:
        payload = json.dumps(self.snapshot(), ensure_ascii=False, indent=2) + '\n'
        self.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.checkpoint.with_suffix(self.checkpoint.suffix + '.tmp')
        with temporary.open('w') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.checkpoint)
        # Make the rename durable where directory fsync is supported.
        flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
        directory_fd = None
        try:
            directory_fd = os.open(self.checkpoint.parent, flags)
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            if directory_fd is not None:
                os.close(directory_fd)

    def before_request(
        self,
        operation: str,
        expected_model: str,
        kwargs: Mapping[str, Any],
    ) -> int:
        input_ceiling = _request_input_bytes(kwargs)
        output_ceiling = int(kwargs.get('max_tokens') or kwargs.get('max_completion_tokens') or 0)
        next_chat = self.chat_requests + (operation == 'chat')
        next_embedding = self.embedding_requests + (operation == 'embedding')
        next_input = self.input_reserved + input_ceiling
        next_output = self.output_reserved + output_ceiling
        failures = []
        if operation == 'chat' and output_ceiling <= 0:
            failures.append('positive chat completion ceiling required')
        if next_chat > self.limits.max_chat_requests:
            failures.append('chat request count')
        if next_embedding > self.limits.max_embedding_requests:
            failures.append('embedding request count')
        if next_input > self.limits.max_input_token_upper_bound:
            failures.append('input token upper bound')
        if next_output > self.limits.max_output_token_ceiling:
            failures.append('output token ceiling')
        if failures:
            self.events.append(
                {
                    'ordinal': len(self.events) + 1,
                    'operation': operation,
                    'expected_model': expected_model,
                    'status': 'blocked_before_dispatch',
                    'limits_exceeded': failures,
                }
            )
            self._write()
            raise BudgetExceeded(', '.join(failures))

        self.chat_requests = next_chat
        self.embedding_requests = next_embedding
        self.input_reserved = next_input
        self.output_reserved = next_output
        event = {
            'ordinal': len(self.events) + 1,
            'operation': operation,
            'expected_model': expected_model,
            'status': 'reserved_before_dispatch',
            'input_token_upper_bound': input_ceiling,
            'output_token_ceiling': output_ceiling,
        }
        self.events.append(event)
        self._write()
        return len(self.events) - 1

    def failed_request(self, request_id: int, exc: BaseException) -> None:
        self.events[request_id].update(
            {
                'status': 'failed_or_uncertain_after_dispatch',
                'error_type': type(exc).__name__,
                'automatic_retry': False,
            }
        )
        self._write()

    def completed_request(self, request_id: int, response: Any) -> None:
        actual = getattr(response, 'model', None)
        expected = self.events[request_id]['expected_model']
        usage = _usage(response)
        breaches = []
        actual_input = usage.get('input_tokens')
        actual_output = usage.get('output_tokens')
        if actual_input is not None and actual_input > self.events[request_id]['input_token_upper_bound']:
            breaches.append('reported input exceeds reserved upper bound')
        if actual_output is not None and actual_output > self.events[request_id]['output_token_ceiling']:
            breaches.append('reported output exceeds reserved ceiling')
        self.events[request_id].update(
            {
                'status': (
                    'budget_breach_after_dispatch'
                    if breaches
                    else ('completed' if actual == expected else 'identity_mismatch')
                ),
                'response_model': actual,
                'usage': usage,
                'automatic_retry': False,
            }
        )
        if breaches:
            self.events[request_id]['limits_exceeded'] = breaches
        self._write()
        if breaches:
            raise BudgetExceeded(', '.join(breaches))

    def snapshot(self) -> dict[str, Any]:
        actual_input = sum(
            int(event.get('usage', {}).get('input_tokens') or 0) for event in self.events
        )
        actual_output = sum(
            int(event.get('usage', {}).get('output_tokens') or 0) for event in self.events
        )
        return {
            'limits': asdict(self.limits),
            'reserved': {
                'chat_requests': self.chat_requests,
                'embedding_requests': self.embedding_requests,
                'input_token_upper_bound': self.input_reserved,
                'output_token_ceiling': self.output_reserved,
            },
            'actual_reported': {
                'input_tokens': actual_input,
                'output_tokens': actual_output,
            },
            'uncertain_requests': sum(
                event['status'] == 'failed_or_uncertain_after_dispatch' for event in self.events
            ),
            'events': self.events,
            'content_or_credentials_recorded': False,
        }


def cost_summary(
    snapshot: Mapping[str, Any],
    *,
    chat_input_per_million: float | None,
    chat_output_per_million: float | None,
    embedding_input_per_million: float | None,
) -> dict[str, Any]:
    actual_usd = 0.0
    usage_complete = True
    pricing_known = all(
        rate is not None
        for rate in (
            chat_input_per_million,
            chat_output_per_million,
            embedding_input_per_million,
        )
    )
    for event in snapshot['events']:
        if event.get('status') != 'completed':
            if event.get('status') != 'blocked_before_dispatch':
                usage_complete = False
            continue
        usage = event.get('usage', {})
        input_tokens = usage.get('input_tokens')
        output_tokens = usage.get('output_tokens')
        if input_tokens is None or (event['operation'] == 'chat' and output_tokens is None):
            usage_complete = False
            continue
        if event['operation'] == 'chat':
            if pricing_known:
                actual_usd += input_tokens * chat_input_per_million / 1_000_000
                actual_usd += output_tokens * chat_output_per_million / 1_000_000
        else:
            if pricing_known:
                actual_usd += input_tokens * embedding_input_per_million / 1_000_000
    limits = snapshot['limits']
    reserved_usd = None
    if pricing_known:
        conservative_input_rate = max(chat_input_per_million, embedding_input_per_million)
        reserved_usd = (
            limits['max_input_token_upper_bound'] * conservative_input_rate
            + limits['max_output_token_ceiling'] * chat_output_per_million
        ) / 1_000_000
    return {
        'rates_usd_per_million_tokens': {
            'chat_input': chat_input_per_million,
            'chat_output': chat_output_per_million,
            'embedding_input': embedding_input_per_million,
        },
        'conservative_reserved_ceiling_usd': reserved_usd,
        'pricing_known': pricing_known,
        'actual_estimated_usd': actual_usd if usage_complete and pricing_known else None,
        'actual_usage_complete': usage_complete,
        'method': 'reserved input uses the higher chat/embedding input rate',
    }


def smoke_row() -> dict[str, Any]:
    return {
        'question_id': SMOKE_QUESTION_ID,
        'question_type': 'synthetic-native-connectivity',
        'question': SMOKE_QUERY,
        'haystack_session_ids': ['smoke-session-1', 'smoke-session-2'],
        'haystack_dates': ['2026/09/12 (Sat) 10:00', '2026/09/12 (Sat) 11:00'],
        'haystack_sessions': [
            [{'role': 'user', 'content': 'My preferred tea is sencha.'}],
            [{'role': 'user', 'content': 'I now prefer oolong tea instead of sencha.'}],
        ],
    }


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    password_file = ROOT / '.runtime/graphiti-neo4j/password'
    if not env.get('GRAPHITI_NEO4J_PASSWORD') and password_file.is_file():
        env['GRAPHITI_NEO4J_PASSWORD'] = password_file.read_text().strip()
    env.setdefault('GRAPHITI_NEO4J_URI', 'bolt://127.0.0.1:17687')
    env.setdefault('GRAPHITI_NEO4J_USER', 'neo4j')
    env.setdefault('GRAPHITI_NEO4J_DATABASE', 'neo4j')
    env.setdefault('GRAPHITI_LLM_MODEL', 'vertex_ai/gemini-3.8-flash')
    env.setdefault('GRAPHITI_SMALL_MODEL', 'vertex_ai/gemini-3.8-flash')
    env.setdefault('GRAPHITI_EMBED_MODEL', 'text-embedding-3-large')
    env.setdefault('GRAPHITI_EMBED_DIM', '3072')
    env.setdefault('GRAPHITI_MAX_TOKENS', '4096')
    env.setdefault('GRAPHITI_REQUEST_TIMEOUT_SECONDS', '90')
    env.setdefault('SEMAPHORE_LIMIT', '2')
    return env


def _edge_record(edge: Any) -> dict[str, Any]:
    record = {}
    for field in (
            'uuid',
            'fact',
            'source_node_uuid',
            'target_node_uuid',
            'created_at',
            'expired_at',
            'valid_at',
            'invalid_at',
            'reference_time',
            'episodes',
    ):
        value = getattr(edge, field, None)
        record[field] = value.isoformat() if isinstance(value, datetime) else value
    return record


async def execute(args: argparse.Namespace, run: BenchmarkRun) -> dict[str, Any]:
    limits = Reservation(
        max_chat_requests=args.max_chat_requests,
        max_embedding_requests=args.max_embedding_requests,
        max_input_token_upper_bound=args.max_input_token_upper_bound,
        max_output_token_ceiling=args.max_output_token_ceiling,
    )
    ledger = UsageLedger(limits, ROOT / '.runtime/graphiti-native-smoke-ledger.json')
    graphiti = None
    phase_seconds: dict[str, float] = {}
    results: list[Any] = []
    edges: list[Any] = []
    failure: BaseException | None = None
    close_failure_type: str | None = None
    try:
        graphiti = build_native_graphiti(_environment(), request_observer=ledger)
        # build_native_graphiti establishes EMBEDDING_DIM before any graphiti_core import.
        from graphiti_core.nodes import EpisodeType
        started = perf_counter()
        existing, _, _ = await graphiti.driver.execute_query(
            'SHOW INDEXES YIELD name, state RETURN name, state',
            routing_='r',
        )
        if not existing:
            await graphiti.build_indices_and_constraints(delete_existing=False)
        elif not all(record['state'] == 'ONLINE' for record in existing):
            raise RuntimeError('isolated Neo4j has a non-ONLINE index')
        phase_seconds['build_indices'] = perf_counter() - started
        records, _, _ = await graphiti.driver.execute_query(
            'MATCH (n) RETURN count(n) AS count',
            routing_='r',
        )
        node_count = int(records[0]['count'])
        if node_count:
            raise RuntimeError(f'isolated Neo4j is not empty: {node_count} graph nodes')

        started = perf_counter()
        row = smoke_row()
        gid = group_id(SMOKE_QUESTION_ID)
        previous_episode_uuid = None
        for session_id, date, turns in zip(
            row['haystack_session_ids'],
            row['haystack_dates'],
            row['haystack_sessions'],
            strict=True,
        ):
            turn = turns[0]
            result = await graphiti.add_episode(
                name=f'{SMOKE_QUESTION_ID}:{session_id}:0',
                episode_body=f'{turn["role"]}: {turn["content"]}',
                source_description='synthetic WI14 native Graphiti connectivity smoke',
                reference_time=datetime.strptime(date, '%Y/%m/%d (%a) %H:%M').replace(
                    tzinfo=timezone.utc
                ),
                source=EpisodeType.message,
                group_id=gid,
                previous_episode_uuids=[previous_episode_uuid] if previous_episode_uuid else None,
            )
            previous_episode_uuid = result.episode.uuid
            results.append(result)
        phase_seconds['ingest_two_episodes'] = perf_counter() - started

        started = perf_counter()
        edges = await graphiti.search(SMOKE_QUERY, group_ids=[gid], num_results=10)
        phase_seconds['native_search'] = perf_counter() - started
    except BaseException as exc:
        failure = exc
    finally:
        if graphiti is not None:
            try:
                await graphiti.close()
            except BaseException as close_failure:
                close_failure_type = type(close_failure).__name__
                if failure is None:
                    failure = close_failure

    request_snapshot = ledger.snapshot()
    payload = {
        'status': 'completed' if failure is None else 'failed',
        'system': 'native open-source Graphiti; not hosted Zep',
        'graphiti_version': GRAPHITI_VERSION,
        'graphiti_commit': GRAPHITI_COMMIT,
        'smoke': {
            'synthetic': True,
            'episodes': 2,
            'query': SMOKE_QUERY,
            'answer_generation': False,
            'phase_seconds': phase_seconds,
            'ingestion_result_counts': [
                {'nodes': len(result.nodes), 'edges': len(result.edges)} for result in results
            ],
            'search_edges': [_edge_record(edge) for edge in edges],
        },
        'requests': request_snapshot,
        'cost': cost_summary(
            request_snapshot,
            chat_input_per_million=args.chat_input_usd_per_million,
            chat_output_per_million=args.chat_output_usd_per_million,
            embedding_input_per_million=args.embedding_input_usd_per_million,
        ),
        'retry_policy': {
            'openai_sdk_max_retries': 0,
            'graphiti_generic_client_retries': 0,
            'uncertain_failure_action': 'abort; never automatically replay',
        },
        'failure': {'type': type(failure).__name__} if failure else None,
        'close_failure_type': close_failure_type,
    }
    try:
        run.write_json(args.output, payload)
    finally:
        ledger.close()
    if failure:
        raise RuntimeError(f'native smoke failed ({type(failure).__name__})') from None
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-native-paid-smoke', action='store_true')
    parser.add_argument(
        '--output',
        type=Path,
        default=ROOT / 'docs/benchmarks-next/graphiti-native-smoke.json',
    )
    parser.add_argument('--max-chat-requests', type=int, default=24)
    parser.add_argument('--max-embedding-requests', type=int, default=64)
    parser.add_argument('--max-input-token-upper-bound', type=int, default=500_000)
    parser.add_argument('--max-output-token-ceiling', type=int, default=98_304)
    parser.add_argument('--chat-input-usd-per-million', type=float)
    parser.add_argument('--chat-output-usd-per-million', type=float)
    parser.add_argument('--embedding-input-usd-per-million', type=float)
    add_provenance_argument(parser)
    args = parser.parse_args()
    if not args.execute_native_paid_smoke:
        parser.error('refusing network dispatch without --execute-native-paid-smoke')

    run = BenchmarkRun(
        allow_dirty=args.allow_dirty,
        requirements=ROOT / 'benchmarks/requirements-graphiti-native.txt',
        sources=[
            Path(__file__),
            ROOT / 'benchmarks/graphiti_native_preflight.py',
            ROOT / 'benchmarks/provenance.py',
            ROOT / 'benchmarks/requirements-graphiti-native.txt',
        ],
    )
    import asyncio

    asyncio.run(execute(args, run))


if __name__ == '__main__':
    main()
