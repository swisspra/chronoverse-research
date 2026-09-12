"""Zero-call preflight and native Graphiti adapter plan for LongMemEval-S.

This module prepares Graphiti's real ``add_episode`` and ``search`` calls. Its
CLI only writes an inventory; it never initializes Graphiti, connects to Neo4j,
or dispatches model requests.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import socket
from types import SimpleNamespace
from typing import Any, Mapping, Protocol

from benchmarks.provenance import BenchmarkRun, add_provenance_argument


ROOT = Path(__file__).resolve().parents[1]
GRAPHITI_VERSION = '0.30.2'
GRAPHITI_TAG = 'v0.30.2'
GRAPHITI_COMMIT = 'eaa4128681bc53487138a4bbc22d58336ebe70d2'
GRAPHITI_WHEEL_SHA256 = '97674a49514130db175faecf23221ce9338240be3cbe13a7e23e5a5033892b9f'
GRAPHITI_SDIST_SHA256 = 'b8ac6999705d350ebb53d799505d49b76f5d74c20265a09df4094645b5d8ada9'
NEO4J_IMAGE = (
    'neo4j:5.26.2@sha256:'
    '099b9f74968c123209972835417985ed2a1cc19c0422c0753a313e26a736c365'
)
LONGMEMEVAL_REVISION = '98d7416c24c778c2fee6e6f3006e7a073259d48f'
LONGMEMEVAL_SHA256 = 'd6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442'
DATE_FORMAT = '%Y/%m/%d (%a) %H:%M'
ABILITY_ORDER = (
    'single-session-user',
    'multi-session',
    'single-session-preference',
    'temporal-reasoning',
    'knowledge-update',
    'single-session-assistant',
)


@dataclass(frozen=True)
class EpisodePlan:
    """One native ``EpisodeType.message`` call, with no answer annotations."""

    name: str
    episode_body: str
    source_description: str
    reference_time: datetime
    group_id: str
    source: str = 'message'


class NativeGraphiti(Protocol):
    """Structural subset used by the adapter; the production object is Graphiti."""

    async def add_episode(self, **kwargs: Any) -> Any: ...

    async def search(self, query: str, **kwargs: Any) -> Any: ...


class ModelIdentityError(RuntimeError):
    """The provider served a model other than the frozen benchmark model."""


class ProviderRequestError(RuntimeError):
    """A provider request failed; its potentially sensitive detail is suppressed."""


class _CheckedCreate:
    def __init__(
        self,
        delegate: Any,
        expected_model: str,
        operation: str,
        observer: Any = None,
    ):
        self._delegate = delegate
        self._expected_model = expected_model
        self._operation = operation
        self._observer = observer

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        request_id = (
            self._observer.before_request(self._operation, self._expected_model, kwargs)
            if self._observer
            else None
        )
        try:
            response = await self._delegate.create(*args, **kwargs)
        except BaseException as exc:
            if self._observer:
                self._observer.failed_request(request_id, exc)
            raise ProviderRequestError(
                f'{self._operation} provider request failed ({type(exc).__name__})'
            ) from None
        actual = getattr(response, 'model', None)
        if self._observer:
            self._observer.completed_request(request_id, response)
        if actual != self._expected_model:
            raise ModelIdentityError(
                f'{self._operation} response.model mismatch: '
                f'expected {self._expected_model!r}, got {actual!r}'
            )
        return response


class IdentityCheckedAsyncOpenAI:
    """Minimal AsyncOpenAI facade that rejects silent model substitution."""

    def __init__(
        self,
        delegate: Any,
        *,
        chat_model: str | None = None,
        embedding_model: str | None = None,
        observer: Any = None,
    ):
        if not chat_model and not embedding_model:
            raise ValueError('at least one expected model is required')
        if chat_model:
            self.chat = SimpleNamespace(
                completions=_CheckedCreate(
                    delegate.chat.completions,
                    chat_model,
                    'chat',
                    observer,
                )
            )
        if embedding_model:
            self.embeddings = _CheckedCreate(
                delegate.embeddings,
                embedding_model,
                'embedding',
                observer,
            )


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if not value:
        raise RuntimeError(f'{name} is required for native Graphiti execution')
    return value


def build_native_graphiti(
    environ: Mapping[str, str] = os.environ,
    *,
    request_observer: Any = None,
) -> Any:
    """Build the pinned native client graph without issuing requests.

    Callers must still invoke ``build_indices_and_constraints`` before ingest.
    The wrapper checks every chat and embedding response's exact ``model`` field.
    """

    dimension = int(environ.get('GRAPHITI_EMBED_DIM', '3072'))
    if dimension <= 0:
        raise ValueError('GRAPHITI_EMBED_DIM must be positive')
    os.environ['GRAPHITI_TELEMETRY_ENABLED'] = 'false'
    os.environ['EMBEDDING_DIM'] = str(dimension)
    # Provider transports can include response bodies in debug logs. The boundary
    # wrapper below emits only sanitized exception types to Graphiti.
    for logger_name in ('openai', 'httpx', 'httpcore'):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    from graphiti_core import Graphiti
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    from graphiti_core.driver.neo4j_driver import Neo4jDriver
    from graphiti_core.embedder.client import EMBEDDING_DIM
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
    from openai import AsyncOpenAI

    class NoRetryOpenAIGenericClient(OpenAIGenericClient):
        async def _generate_response_with_retry(self, *args: Any, **kwargs: Any) -> Any:
            return await self._generate_response(*args, **kwargs)

    if EMBEDDING_DIM != dimension:
        raise RuntimeError(
            'graphiti_core was imported with a different EMBEDDING_DIM; '
            'restart the process with the frozen dimension'
        )

    llm_model = _required(environ, 'GRAPHITI_LLM_MODEL')
    small_model = _required(environ, 'GRAPHITI_SMALL_MODEL')
    llm_config = LLMConfig(
        api_key=_required(environ, 'GRAPHITI_LLM_API_KEY'),
        model=llm_model,
        small_model=small_model,
        base_url=_required(environ, 'GRAPHITI_LLM_BASE_URL'),
    )
    raw_chat = AsyncOpenAI(
        api_key=llm_config.api_key,
        base_url=llm_config.base_url,
        max_retries=0,
        timeout=float(environ.get('GRAPHITI_REQUEST_TIMEOUT_SECONDS', '90')),
    )
    checked_chat = IdentityCheckedAsyncOpenAI(
        raw_chat,
        chat_model=llm_model,
        observer=request_observer,
    )
    structured_mode = environ.get('GRAPHITI_STRUCTURED_OUTPUT_MODE', 'json_schema')
    if structured_mode not in {'json_schema', 'json_object'}:
        raise ValueError('GRAPHITI_STRUCTURED_OUTPUT_MODE must be json_schema or json_object')
    llm_client = NoRetryOpenAIGenericClient(
        config=llm_config,
        client=checked_chat,
        max_tokens=int(environ.get('GRAPHITI_MAX_TOKENS', '4096')),
        structured_output_mode=structured_mode,
    )

    embedding_model = _required(environ, 'GRAPHITI_EMBED_MODEL')
    raw_embedding = AsyncOpenAI(
        api_key=_required(environ, 'GRAPHITI_EMBED_API_KEY'),
        base_url=_required(environ, 'GRAPHITI_EMBED_BASE_URL'),
        max_retries=0,
        timeout=float(environ.get('GRAPHITI_REQUEST_TIMEOUT_SECONDS', '90')),
    )
    checked_embedding = IdentityCheckedAsyncOpenAI(
        raw_embedding,
        embedding_model=embedding_model,
        observer=request_observer,
    )
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key='identity-checked-client',
            base_url='http://unused.invalid/v1',
            embedding_model=embedding_model,
            embedding_dim=dimension,
        ),
        client=checked_embedding,
    )

    driver = Neo4jDriver(
        uri=_required(environ, 'GRAPHITI_NEO4J_URI'),
        user=_required(environ, 'GRAPHITI_NEO4J_USER'),
        password=_required(environ, 'GRAPHITI_NEO4J_PASSWORD'),
        database=environ.get('GRAPHITI_NEO4J_DATABASE', 'neo4j'),
    )
    return Graphiti(
        graph_driver=driver,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=OpenAIRerankerClient(config=llm_config, client=checked_chat),
        max_coroutines=int(environ.get('SEMAPHORE_LIMIT', '2')),
    )


def parse_lme_date(value: str) -> datetime:
    """Parse the dataset's minute timestamp as UTC, as upstream's eval does."""

    return datetime.strptime(value, DATE_FORMAT).replace(tzinfo=timezone.utc)


def group_id(question_id: str) -> str:
    """Create a valid, stable Graphiti partition without exposing answer labels."""

    digest = hashlib.sha256(question_id.encode()).hexdigest()[:20]
    return f'lme_s_{digest}'


def episode_plan(row: Mapping[str, Any]) -> list[EpisodePlan]:
    """Create chronological per-message episodes from one LongMemEval-S row.

    Sessions are ordered by reference timestamp, then original dataset order.
    Turns retain their session order. Only role and content cross the ingestion
    boundary; ``answer``, ``answer_session_ids``, and ``has_answer`` do not.
    """

    sessions = row['haystack_sessions']
    session_ids = row['haystack_session_ids']
    dates = row['haystack_dates']
    if not (len(sessions) == len(session_ids) == len(dates)):
        raise ValueError('LongMemEval session, id, and date arrays differ in length')

    ordered = sorted(
        enumerate(zip(session_ids, dates, sessions, strict=True)),
        key=lambda item: (parse_lme_date(item[1][1]), item[0]),
    )
    planned: list[EpisodePlan] = []
    qid = str(row['question_id'])
    gid = group_id(qid)
    for original_session_index, (session_id, date, turns) in ordered:
        reference_time = parse_lme_date(date)
        for turn_index, turn in enumerate(turns):
            role = str(turn['role'])
            content = str(turn['content'])
            planned.append(
                EpisodePlan(
                    name=f'{qid}:{session_id}:{turn_index}',
                    episode_body=f'{role}: {content}',
                    source_description=(
                        'LongMemEval-S cleaned; '
                        f'session={session_id}; dataset_session_index={original_session_index}'
                    ),
                    reference_time=reference_time,
                    group_id=gid,
                )
            )
    return planned


async def native_ingest_question(graphiti: NativeGraphiti, row: Mapping[str, Any]) -> list[Any]:
    """Await Graphiti's native ingestion sequentially, per upstream guidance."""

    # Import only on the paid/executing path. Merely running the preflight stays
    # independent of Graphiti and cannot initialize its opt-out telemetry.
    from graphiti_core.nodes import EpisodeType

    results = []
    for episode in episode_plan(row):
        values = asdict(episode)
        values['source'] = EpisodeType.message
        results.append(await graphiti.add_episode(**values))
    return results


async def native_search(graphiti: NativeGraphiti, row: Mapping[str, Any], limit: int = 10) -> Any:
    """Use Graphiti's basic native edge search with its RRF recipe."""

    return await graphiti.search(
        str(row['question']),
        group_ids=[group_id(str(row['question_id']))],
        num_results=limit,
    )


def select_gold_free_pilot(rows: list[Mapping[str, Any]]) -> list[str]:
    """Select the lexicographically first question ID in every ability stratum."""

    by_type: dict[str, list[str]] = {ability: [] for ability in ABILITY_ORDER}
    for row in rows:
        ability = str(row['question_type'])
        if ability in by_type:
            by_type[ability].append(str(row['question_id']))
    missing = [ability for ability, ids in by_type.items() if not ids]
    if missing:
        raise ValueError(f'missing LongMemEval abilities: {missing}')
    return [sorted(by_type[ability])[0] for ability in ABILITY_ORDER]


def _port_open(host: str, port: int, timeout: float = 0.1) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def docker_inventory() -> dict[str, Any]:
    """Report local reachability without starting Docker or any service."""

    socket_path = Path.home() / '.docker/run/docker.sock'
    return {
        'cli_detected': any(
            (Path(directory) / 'docker').is_file()
            for directory in os.environ.get('PATH', '').split(os.pathsep)
            if directory
        ),
        'desktop_linux_socket_present': socket_path.exists(),
        'dedicated_http_port_17474_open': _port_open('127.0.0.1', 17474),
        'dedicated_bolt_port_17687_open': _port_open('127.0.0.1', 17687),
        'mutation_performed': False,
    }


def package_inventory() -> dict[str, Any]:
    try:
        installed = importlib.metadata.version('graphiti-core')
    except importlib.metadata.PackageNotFoundError:
        installed = None
    return {
        'required_distribution': f'graphiti-core=={GRAPHITI_VERSION}',
        'installed_in_current_interpreter': installed,
        'version_matches': installed == GRAPHITI_VERSION,
    }


def provider_inventory(environ: Mapping[str, str]) -> dict[str, Any]:
    """Record readiness without serializing credentials or private endpoints."""

    mode = environ.get('GRAPHITI_STRUCTURED_OUTPUT_MODE', 'json_schema')
    if mode not in {'json_schema', 'json_object'}:
        raise ValueError('GRAPHITI_STRUCTURED_OUTPUT_MODE must be json_schema or json_object')
    dimension = int(environ.get('GRAPHITI_EMBED_DIM', '3072'))
    if dimension <= 0:
        raise ValueError('GRAPHITI_EMBED_DIM must be positive')
    return {
        'adapter': 'OpenAIGenericClient + OpenAIEmbedder',
        'llm_base_url_configured': bool(environ.get('GRAPHITI_LLM_BASE_URL')),
        'llm_api_key_configured': bool(environ.get('GRAPHITI_LLM_API_KEY')),
        'llm_model': environ.get('GRAPHITI_LLM_MODEL'),
        'small_model': environ.get('GRAPHITI_SMALL_MODEL'),
        'structured_output_mode': mode,
        'embedding_base_url_configured': bool(environ.get('GRAPHITI_EMBED_BASE_URL')),
        'embedding_api_key_configured': bool(environ.get('GRAPHITI_EMBED_API_KEY')),
        'embedding_model': environ.get('GRAPHITI_EMBED_MODEL'),
        'embedding_dimension': dimension,
        'secrets_serialized': False,
    }


def inventory(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row['question_type']) for row in rows)
    plans = [episode_plan(row) for row in rows]
    episode_counts = [len(plan) for plan in plans]
    return {
        'questions': len(rows),
        'question_types': dict(sorted(counts.items())),
        'abstention_questions': sum(str(row['question_id']).endswith('_abs') for row in rows),
        'sessions': sum(len(row['haystack_sessions']) for row in rows),
        'native_message_episodes': sum(episode_counts),
        'min_episodes_per_question': min(episode_counts),
        'max_episodes_per_question': max(episode_counts),
        'mean_episodes_per_question': sum(episode_counts) / len(episode_counts),
        'pilot_question_ids': select_gold_free_pilot(rows),
        'ingress_fields': ['question_id', 'haystack_session_ids', 'haystack_dates', 'role', 'content'],
        'excluded_ingress_fields': ['answer', 'answer_session_ids', 'has_answer'],
    }


def protocol() -> dict[str, Any]:
    return {
        'status': 'preflight_only',
        'native_graphiti_ingestion_executed': False,
        'native_graphiti_search_executed': False,
        'answer_generation_executed': False,
        'paid_api_calls': 0,
        'open_source_system': 'Graphiti; Apache-2.0; self-hosted',
        'hosted_system_excluded': 'Zep managed Context Graph service',
        'database': {
            'driver': 'Neo4jDriver',
            'database': 'neo4j',
            'image': NEO4J_IMAGE,
            'indices': 'Graphiti.build_indices_and_constraints(delete_existing=False) once before ingestion',
        },
        'ingestion': {
            'api': 'await Graphiti.add_episode(...)',
            'episode_type': 'EpisodeType.message',
            'unit': 'one LongMemEval turn per episode',
            'ordering': 'sessions ascending reference_time; ties retain dataset order; turns retain session order',
            'execution': 'sequential and awaited within each question partition',
            'partition': 'one deterministic group_id per question',
            'community_updates': False,
            'raw_episode_content': True,
        },
        'search': {
            'api': 'await Graphiti.search(question, group_ids=[group_id], num_results=10)',
            'returned_layer': 'EntityEdge facts',
            'recipe': 'EDGE_HYBRID_SEARCH_RRF',
            'methods': ['edge BM25', 'edge cosine similarity'],
            'reranker': 'reciprocal-rank fusion',
            'limit': 10,
            'cross_encoder_used': False,
            'question_date_filter': False,
        },
        'upstream_defaults_not_silently_used': {
            'default_openai_llm': 'gpt-5.5 medium prompts; gpt-4.1-nano small prompts',
            'generic_openai_compatible_llm': 'gpt-4.1-mini if model omitted',
            'default_embedding': 'text-embedding-3-small truncated to EMBEDDING_DIM=1024',
            'default_cross_encoder': 'gpt-4.1-nano; not invoked by basic Graphiti.search',
            'core_semaphore_limit': 20,
            'planned_pilot_semaphore_limit': 2,
            'telemetry': 'upstream opt-out; planned comparison sets GRAPHITI_TELEMETRY_ENABLED=false',
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--dataset',
        type=Path,
        default=ROOT / '.benchmark-data/longmemeval-s.json',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=ROOT / 'docs/benchmarks-next/graphiti-native-preflight.json',
    )
    add_provenance_argument(parser)
    args = parser.parse_args()
    sources = [
        Path(__file__),
        ROOT / 'benchmarks/provenance.py',
        ROOT / 'benchmarks/requirements-graphiti-native.txt',
        ROOT / 'benchmarks/graphiti-native.compose.yaml',
    ]
    run = BenchmarkRun(
        allow_dirty=args.allow_dirty,
        requirements=ROOT / 'benchmarks/requirements-graphiti-native.txt',
        sources=sources,
    )
    raw = args.dataset.read_bytes()
    if hashlib.sha256(raw).hexdigest() != LONGMEMEVAL_SHA256:
        raise RuntimeError('LongMemEval-S bytes differ from the pinned dataset')
    rows = json.loads(raw)
    if len(rows) != 500:
        raise RuntimeError('LongMemEval-S expected 500 questions')
    payload = {
        'graphiti': {
            'version': GRAPHITI_VERSION,
            'release_tag': GRAPHITI_TAG,
            'commit': GRAPHITI_COMMIT,
            'wheel_sha256': GRAPHITI_WHEEL_SHA256,
            'sdist_sha256': GRAPHITI_SDIST_SHA256,
            'package': package_inventory(),
        },
        'dataset': {
            'name': 'LongMemEval-S cleaned',
            'revision': LONGMEMEVAL_REVISION,
            'sha256': LONGMEMEVAL_SHA256,
            'inventory': inventory(rows),
        },
        'runtime': {
            'docker': docker_inventory(),
            'provider': provider_inventory(os.environ),
        },
        'protocol': protocol(),
        'next_gate': (
            'Record the provider/model price table and a bounded run reservation, then run one '
            'full-question smoke before the frozen six-ability pilot.'
        ),
    }
    run.write_json(args.output, payload)
    print(json.dumps({'status': 'preflight_only', 'paid_api_calls': 0}))


if __name__ == '__main__':
    main()
