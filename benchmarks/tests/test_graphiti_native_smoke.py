import asyncio
import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.graphiti_native_smoke import (
    BudgetExceeded,
    Reservation,
    UsageLedger,
    _request_input_bytes,
    cost_summary,
    smoke_row,
)
import benchmarks.graphiti_native_smoke as smoke_module


def test_request_input_bytes_is_conservative_and_content_independent():
    request = {
        'messages': [{'role': 'user', 'content': 'abcd'}],
        'response_format': {'type': 'json_schema', 'schema': {'required': ['answer']}},
    }
    ascii_size = _request_input_bytes(request)
    unicode_size = _request_input_bytes({'input': ['ชา']})
    assert ascii_size >= len(json.dumps(request, separators=(',', ':')).encode())
    assert unicode_size >= len('ชา'.encode()) + 1024


def test_budget_blocks_before_delegate_dispatch(tmp_path: Path):
    ledger = UsageLedger(
        Reservation(
            max_chat_requests=0,
            max_embedding_requests=0,
            max_input_token_upper_bound=0,
            max_output_token_ceiling=0,
        ),
        tmp_path / 'ledger.json',
    )
    with pytest.raises(BudgetExceeded):
        ledger.before_request('chat', 'model', {'messages': [], 'max_tokens': 1})
    assert ledger.events[-1]['status'] == 'blocked_before_dispatch'
    ledger.close()


def test_chat_requires_positive_completion_reservation(tmp_path: Path):
    ledger = UsageLedger(Reservation(), tmp_path / 'ledger.json')
    with pytest.raises(BudgetExceeded, match='positive chat completion ceiling'):
        ledger.before_request('chat', 'model', {'messages': []})
    ledger.close()


def test_existing_or_concurrently_owned_ledger_is_refused(tmp_path: Path):
    checkpoint = tmp_path / 'ledger.json'
    first = UsageLedger(Reservation(), checkpoint)
    with pytest.raises(RuntimeError, match='another native smoke'):
        UsageLedger(Reservation(), checkpoint)
    first.close()
    checkpoint.write_text('{}')
    with pytest.raises(RuntimeError, match='already exists'):
        UsageLedger(Reservation(), checkpoint)


def test_usage_ledger_records_identity_usage_and_no_content(tmp_path: Path):
    ledger = UsageLedger(Reservation(), tmp_path / 'ledger.json')
    request_id = ledger.before_request(
        'chat',
        'model-a',
        {'messages': [{'role': 'user', 'content': 'sensitive prompt'}], 'max_tokens': 100},
    )
    usage = type('Usage', (), {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15})()
    response = type('Response', (), {'model': 'model-a', 'usage': usage})()
    ledger.completed_request(request_id, response)
    snapshot = ledger.snapshot()
    assert snapshot['actual_reported'] == {'input_tokens': 12, 'output_tokens': 3}
    assert snapshot['events'][0]['status'] == 'completed'
    assert 'sensitive prompt' not in repr(snapshot)
    assert json_text(tmp_path / 'ledger.json').find('sensitive prompt') == -1
    ledger.close()


def test_usage_ledger_fsyncs_file_and_parent_directory(tmp_path: Path, monkeypatch):
    calls = []
    real_fsync = os.fsync

    def recording_fsync(fd):
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, 'fsync', recording_fsync)
    checkpoint = tmp_path / 'ledger.json'
    ledger = UsageLedger(Reservation(), checkpoint)
    ledger.before_request('embedding', 'embed', {'input': ['text']})
    assert len(calls) >= 2
    assert checkpoint.is_file()
    assert not checkpoint.with_suffix('.json.tmp').exists()
    ledger.close()


def test_provider_usage_cannot_exceed_reserved_request(tmp_path: Path):
    ledger = UsageLedger(Reservation(), tmp_path / 'ledger.json')
    request_id = ledger.before_request(
        'chat',
        'model-a',
        {'messages': [], 'max_tokens': 2},
    )
    usage = type(
        'Usage',
        (),
        {'prompt_tokens': 1, 'completion_tokens': 3, 'total_tokens': 4},
    )()
    response = type('Response', (), {'model': 'model-a', 'usage': usage})()
    with pytest.raises(BudgetExceeded, match='reported output'):
        ledger.completed_request(request_id, response)
    event = ledger.snapshot()['events'][0]
    assert event['status'] == 'budget_breach_after_dispatch'
    assert event['usage']['output_tokens'] == 3
    ledger.close()


def test_uncertain_request_is_not_released_or_marked_retryable(tmp_path: Path):
    ledger = UsageLedger(Reservation(), tmp_path / 'ledger.json')
    request_id = ledger.before_request(
        'embedding',
        'embed-a',
        {'input': ['text']},
    )
    ledger.failed_request(request_id, TimeoutError('unknown provider outcome'))
    event = ledger.snapshot()['events'][0]
    assert event['status'] == 'failed_or_uncertain_after_dispatch'
    assert event['automatic_retry'] is False
    assert ledger.embedding_requests == 1
    ledger.close()


def test_cost_reservation_is_conservative_and_missing_usage_is_not_zero(tmp_path: Path):
    ledger = UsageLedger(Reservation(), tmp_path / 'ledger.json')
    request_id = ledger.before_request('chat', 'model', {'messages': [], 'max_tokens': 10})
    response = type('Response', (), {'model': 'model', 'usage': None})()
    ledger.completed_request(request_id, response)
    cost = cost_summary(
        ledger.snapshot(),
        chat_input_per_million=0.75,
        chat_output_per_million=3.75,
        embedding_input_per_million=0.13,
    )
    assert cost['conservative_reserved_ceiling_usd'] == pytest.approx(0.74364)
    assert cost['actual_estimated_usd'] is None
    assert cost['actual_usage_complete'] is False
    ledger.close()


def test_prices_are_unknown_unless_explicitly_supplied(tmp_path: Path):
    ledger = UsageLedger(Reservation(), tmp_path / 'ledger.json')
    request_id = ledger.before_request('embedding', 'embed', {'input': ['text']})
    usage = type('Usage', (), {'prompt_tokens': 5, 'completion_tokens': None})()
    response = type('Response', (), {'model': 'embed', 'usage': usage})()
    ledger.completed_request(request_id, response)
    cost = cost_summary(
        ledger.snapshot(),
        chat_input_per_million=None,
        chat_output_per_million=None,
        embedding_input_per_million=None,
    )
    assert cost['pricing_known'] is False
    assert cost['conservative_reserved_ceiling_usd'] is None
    assert cost['actual_estimated_usd'] is None
    assert cost['actual_usage_complete'] is True
    ledger.close()


def test_failed_request_makes_actual_usage_unknown(tmp_path: Path):
    ledger = UsageLedger(Reservation(), tmp_path / 'ledger.json')
    request_id = ledger.before_request('embedding', 'embed', {'input': ['text']})
    ledger.failed_request(request_id, TimeoutError('do not serialize this detail'))
    cost = cost_summary(
        ledger.snapshot(),
        chat_input_per_million=0.75,
        chat_output_per_million=3.75,
        embedding_input_per_million=0.13,
    )
    assert cost['actual_usage_complete'] is False
    assert cost['actual_estimated_usd'] is None
    assert 'do not serialize this detail' not in json_text(tmp_path / 'ledger.json')
    ledger.close()


def test_close_failure_still_publishes_and_releases_ledger(tmp_path: Path, monkeypatch):
    class BrokenCloseGraphiti:
        async def close(self):
            raise RuntimeError('sensitive close detail')

    class CapturingRun:
        payload = None

        def write_json(self, _path, payload):
            self.payload = payload

    def build_with_pending_reservation(*_args, request_observer, **_kwargs):
        request_observer.before_request('embedding', 'embed', {'input': ['synthetic']})
        return BrokenCloseGraphiti()

    monkeypatch.setattr(smoke_module, 'ROOT', tmp_path)
    monkeypatch.setattr(
        smoke_module,
        'build_native_graphiti',
        build_with_pending_reservation,
    )
    args = SimpleNamespace(
        max_chat_requests=24,
        max_embedding_requests=64,
        max_input_token_upper_bound=500_000,
        max_output_token_ceiling=98_304,
        chat_input_usd_per_million=None,
        chat_output_usd_per_million=None,
        embedding_input_usd_per_million=None,
        output=tmp_path / 'result.json',
    )
    run = CapturingRun()
    with pytest.raises(RuntimeError, match=r'native smoke failed \([A-Za-z]+Error\)') as captured:
        asyncio.run(smoke_module.execute(args, run))
    assert 'sensitive close detail' not in str(captured.value)
    assert run.payload is not None
    assert run.payload['close_failure_type'] == 'RuntimeError'
    assert (tmp_path / '.runtime/graphiti-native-smoke-ledger.json').is_file()

    lock_path = tmp_path / '.runtime/graphiti-native-smoke-ledger.json.lock'
    with lock_path.open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def test_smoke_fixture_is_two_synthetic_chronological_messages():
    row = smoke_row()
    assert sum(len(session) for session in row['haystack_sessions']) == 2
    assert row['haystack_dates'] == sorted(row['haystack_dates'])
    assert 'answer' not in row


def json_text(path: Path) -> str:
    return path.read_text()
