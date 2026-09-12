import asyncio
from datetime import timezone

import pytest

from benchmarks.graphiti_native_preflight import (
    episode_plan,
    group_id,
    IdentityCheckedAsyncOpenAI,
    ModelIdentityError,
    native_search,
    ProviderRequestError,
    provider_inventory,
    select_gold_free_pilot,
)


def row(question_id='q-1', question_type='knowledge-update'):
    return {
        'question_id': question_id,
        'question_type': question_type,
        'question': 'What changed?',
        'answer': 'SECRET GOLD',
        'answer_session_ids': ['late'],
        'haystack_session_ids': ['late', 'early'],
        'haystack_dates': ['2024/01/02 (Tue) 12:00', '2024/01/01 (Mon) 12:00'],
        'haystack_sessions': [
            [{'role': 'user', 'content': 'new fact', 'has_answer': True}],
            [
                {'role': 'user', 'content': 'old fact', 'has_answer': False},
                {'role': 'assistant', 'content': 'ack', 'has_answer': False},
            ],
        ],
    }


def test_episode_plan_is_chronological_and_does_not_leak_gold():
    episodes = episode_plan(row())
    assert [item.episode_body for item in episodes] == [
        'user: old fact',
        'assistant: ack',
        'user: new fact',
    ]
    assert all(item.reference_time.tzinfo == timezone.utc for item in episodes)
    serialized = repr(episodes)
    assert 'SECRET GOLD' not in serialized
    assert 'has_answer' not in serialized
    assert 'answer_session_ids' not in serialized


def test_group_id_is_stable_safe_and_question_specific():
    first = group_id('question / with unsafe characters')
    assert first == group_id('question / with unsafe characters')
    assert first != group_id('another')
    assert first.startswith('lme_s_')
    assert first.replace('_', '').isalnum()


def test_episode_plan_rejects_misaligned_session_arrays():
    broken = row()
    broken['haystack_dates'] = []
    with pytest.raises(ValueError, match='differ in length'):
        episode_plan(broken)


def test_provider_inventory_never_serializes_secrets_or_endpoints():
    secret = 'do-not-publish-this-key'
    endpoint = 'https://private-host.example/v1'
    result = provider_inventory(
        {
            'GRAPHITI_LLM_API_KEY': secret,
            'GRAPHITI_LLM_BASE_URL': endpoint,
            'GRAPHITI_LLM_MODEL': 'model-a',
            'GRAPHITI_EMBED_API_KEY': secret,
            'GRAPHITI_EMBED_BASE_URL': endpoint,
            'GRAPHITI_EMBED_MODEL': 'embed-a',
        }
    )
    assert result['llm_api_key_configured'] is True
    assert result['embedding_api_key_configured'] is True
    assert secret not in repr(result)
    assert endpoint not in repr(result)


def test_pilot_selection_is_gold_free_and_stratified():
    abilities = (
        'single-session-user',
        'multi-session',
        'single-session-preference',
        'temporal-reasoning',
        'knowledge-update',
        'single-session-assistant',
    )
    rows = []
    for ability in abilities:
        rows.extend([row(f'z-{ability}', ability), row(f'a-{ability}', ability)])
    assert select_gold_free_pilot(rows) == [f'a-{ability}' for ability in abilities]


def test_identity_guard_accepts_exact_model_and_rejects_substitution():
    class Endpoint:
        def __init__(self, model):
            self.model = model

        async def create(self, **_kwargs):
            return type('Response', (), {'model': self.model})()

    exact = type(
        'Client',
        (),
        {'chat': type('Chat', (), {'completions': Endpoint('vertex_ai/gemini-3.8-flash')})()},
    )()
    guarded = IdentityCheckedAsyncOpenAI(
        exact,
        chat_model='vertex_ai/gemini-3.8-flash',
    )
    response = asyncio.run(guarded.chat.completions.create())
    assert response.model == 'vertex_ai/gemini-3.8-flash'

    substituted = type(
        'Client',
        (),
        {'embeddings': Endpoint('text-embedding-3-small')},
    )()
    guarded_embedding = IdentityCheckedAsyncOpenAI(
        substituted,
        embedding_model='text-embedding-3-large',
    )
    with pytest.raises(ModelIdentityError, match='response.model mismatch'):
        asyncio.run(guarded_embedding.embeddings.create())


def test_identity_guard_sanitizes_provider_exception_before_upstream_sees_it():
    secret = 'secret-response-body-and-key'

    class Endpoint:
        async def create(self, **_kwargs):
            raise RuntimeError(secret)

    client = type(
        'Client',
        (),
        {'chat': type('Chat', (), {'completions': Endpoint()})()},
    )()
    guarded = IdentityCheckedAsyncOpenAI(client, chat_model='model')
    with pytest.raises(ProviderRequestError) as captured:
        asyncio.run(guarded.chat.completions.create())
    assert type(captured.value).__name__ == 'ProviderRequestError'
    assert 'RuntimeError' in str(captured.value)
    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None


def test_search_calls_native_basic_api_with_partition_and_limit():
    calls = []

    class FakeGraphiti:
        async def search(self, query, **kwargs):
            calls.append((query, kwargs))
            return ['edge']

    result = asyncio.run(native_search(FakeGraphiti(), row(), limit=7))
    assert result == ['edge']
    assert calls == [
        (
            'What changed?',
            {'group_ids': [group_id('q-1')], 'num_results': 7},
        )
    ]
