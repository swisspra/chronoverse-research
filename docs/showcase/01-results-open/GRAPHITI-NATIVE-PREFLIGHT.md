# Native Graphiti preflight for WI14

> **STATUS · CURRENT** — original dated 2026-09-13 01:27 · chain and replacements in [`00-START-HERE/VERSION-MAP.md`](../00-START-HERE/VERSION-MAP.md) · preflight, not a result; the Neo4j run is still open

This freezes a **native open-source Graphiti** comparison before any model request. No Graphiti ingestion, search, answer generation, hosted Zep request, or paid API call was made in this preflight.

## Frozen upstream system

| Item | Frozen value |
|---|---|
| Package | `graphiti-core==0.30.2` |
| Release | [`v0.30.2`](https://github.com/getzep/graphiti/releases/tag/v0.30.2), published 2026-09-08 |
| Commit | [`eaa4128681bc53487138a4bbc22d58336ebe70d2`](https://github.com/getzep/graphiti/commit/eaa4128681bc53487138a4bbc22d58336ebe70d2) |
| License | Apache-2.0 in the tagged `pyproject.toml` and repository |
| PyPI wheel SHA-256 | `97674a49514130db175faecf23221ce9338240be3cbe13a7e23e5a5033892b9f` |
| PyPI sdist SHA-256 | `b8ac6999705d350ebb53d799505d49b76f5d74c20265a09df4094645b5d8ada9` |
| Python | `>=3.10,<4`; the isolated setup uses Python 3.12 |
| OpenAI SDK | `2.32.0`, matching the tagged upstream `uv.lock` |
| Graph database | Neo4j `5.26.2`, matching the tagged root Compose file |
| Neo4j image | `neo4j:5.26.2@sha256:099b9f74968c123209972835417985ed2a1cc19c0422c0753a313e26a736c365` |

The release tag points directly to the commit above. The moving `main` branch is not a benchmark dependency. Graphiti versions before 0.28.2 had a published Cypher-injection issue; 0.30.2 is after the fix, but the comparison still binds Neo4j to loopback and does not expose Graphiti's HTTP service.

The package metadata permits any `openai>=1.91.0`. On 2026-09-13 an unconstrained resolve selected `openai==3.13.0`, whose `httpx2` dependency did not satisfy Graphiti 0.30.2's direct `import httpx`; importing `graphiti_core` failed with `ModuleNotFoundError: No module named 'httpx'`. The isolated lock therefore pins `openai==2.32.0`, the exact version in the tagged upstream `uv.lock`, rather than adding an unproven compatibility shim.

Graphiti is the Apache-2.0 framework run locally with a third-party graph database and caller-supplied models. [Zep](https://help.getzep.com/zep-vs-graphiti) is a separate managed product with proprietary storage, extraction, reranking, governance, and operating layers. A local Graphiti result must not be labeled a Zep result, and Zep's published LongMemEval score is not substituted for this run.

## Exact native path

The setup calls the APIs from the pinned package:

1. Construct `Neo4jDriver(uri, user, password, database="neo4j")` and pass it to `Graphiti` with explicit LLM and embedding clients.
2. Run `await graphiti.build_indices_and_constraints(delete_existing=False)` once on the empty dedicated database.
3. Give every LongMemEval-S question its own deterministic `group_id`. This prevents memory from another independently authored test row from entering the answer context.
4. Sort sessions by their dataset timestamp, retaining dataset order for ties. Within each session retain turn order.
5. Ingest each turn sequentially with `await graphiti.add_episode(...)`, `EpisodeType.message`, body `"role: content"`, and the session timestamp as `reference_time`. The pinned code says sequential calls should be awaited. This also matches the per-message unit used by Graphiti's bundled LongMemEval graph-building evaluation, while correcting that example's non-chronological dataset iteration.
6. Search with `await graphiti.search(question, group_ids=[group_id], num_results=10)`. In 0.30.2 this basic method uses `EDGE_HYBRID_SEARCH_RRF`: edge BM25 plus edge cosine similarity, fused with RRF. It returns up to ten `EntityEdge` facts. It does not invoke the configured LLM cross-encoder.
7. Preserve every returned edge's UUID, fact, source/target node UUIDs, `created_at`, `expired_at`, `valid_at`, `invalid_at`, and `episodes` provenance before producing the answer context.

The basic search call has no `reference_time` argument and the empty default `SearchFilters` do not enforce the LongMemEval `question_date`. Graphiti returns temporal edge fields, but calling the basic native search is not evidence of a historical as-of cutoff. Adding date filters would be a separate declared arm, not a hidden correction to the native default.

Graphiti's bundled LongMemEval file and test are useful implementation evidence, not a complete answer benchmark: the test uses the oracle subset, accepts caller-supplied caps, compares graph-building outputs with another LLM, and does not report the LongMemEval-S answer accuracy required by WI14.

## Default model behavior and proxy adaptation

The zero-argument Graphiti clients in 0.30.2 are:

- `OpenAIClient`: `gpt-5.5` for medium prompts and `gpt-4.1-nano` for small prompts.
- `OpenAIEmbedder`: `text-embedding-3-small`, sliced to `EMBEDDING_DIM`; the package default is 1,024 dimensions.
- `OpenAIRerankerClient`: `gpt-4.1-nano`. Basic `Graphiti.search` does not use it; advanced `search_()` does.
- Core concurrency: `SEMAPHORE_LIMIT=20`. The pilot freezes it at 2 until the provider's rate limits are measured.
- Raw episode storage: enabled. Community updates in `add_episode`: disabled.
- Anonymous PostHog telemetry: opt-out upstream. The comparison explicitly sets `GRAPHITI_TELEMETRY_ENABLED=false`.

For an OpenAI-compatible proxy, the [tagged provider guidance](https://github.com/getzep/graphiti/blob/v0.30.2/README.md#using-graphiti-with-openai-compatible-providers-and-local-llms) requires `OpenAIGenericClient`, an explicit `LLMConfig(model, small_model, base_url, api_key)`, and an explicit `OpenAIEmbedderConfig`. The prepared target is `vertex_ai/gemini-3.8-flash` for both Graphiti model sizes and `text-embedding-3-large` at 3,072 dimensions for embeddings. This records a configuration target, not a completed Graphiti request. A wrapper rejects every chat or embedding response unless `response.model` exactly matches the requested identity, preventing silent proxy substitution. `json_schema` is the frozen first choice; `json_object` is allowed only as a recorded compatibility fallback after a schema smoke test fails. Graphiti depends on structured JSON during extraction and deduplication, so endpoint compatibility cannot be inferred from a successful ordinary chat request.

The two-episode smoke disables retries in both layers: OpenAI SDK `max_retries=0`, and a Graphiti generic-client subclass bypasses the upstream tenacity wrapper. An uncertain timeout or connection failure is recorded and aborts the run without replay. Before every network dispatch, the runner reserves request count, the complete serialized request plus a fixed framing allowance as a conservative BPE-token ceiling, and the requested maximum output tokens. It checkpoints actual provider usage and `response.model` without prompts, URLs, or credentials. A locked, pre-existing ledger is never overwritten. Frozen smoke ceilings are 24 chat calls, 64 embedding calls, 500,000 input-token upper bound, and 98,304 maximum output tokens; `GRAPHITI_MAX_TOKENS=4096` sets the generic client default; native Graphiti helpers can override it. The ledger reserves each actual outgoing request cap and enforces the aggregate ceiling. In the completed smoke, five chat requests specified4,096 tokens and two specified16,384 tokens (53,248 reserved output tokens total). The default is therefore not a hard per-call maximum. Prices default to unknown because the current proxy's billing contract is not established. For a separately labeled OpenRouter run only, explicit rates of $0.75/M chat input, $3.75/M chat output, and $0.13/M embedding input imply a deliberately conservative reservation of at most $0.74364. Actual cost is reported only when all rates are explicit, every dispatched request completes, and every response includes the required usage; missing or uncertain usage is never treated as zero.

The first run uses the already verified current proxy and exact `vertex_ai/gemini-3.8-flash` identity. If its structured-output route fails, an OpenRouter fallback must use a fresh empty Neo4j runtime and a newly archived ledger, with separate provenance, model identity, explicit price rates, reservation, and result file. It must not resume or mix requests from the failed provider run.

Azure OpenAI is also a native path in the tagged repository: use `AsyncOpenAI` with `https://<resource>.openai.azure.com/openai/v1/`, `AzureOpenAILLMClient`, and `AzureOpenAIEmbedderClient`, where model strings are Azure deployment names. That is a future deployment option, not part of this local preflight.

## LongMemEval-S scale and cost gate

The pinned local dataset has SHA-256 `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`, 500 questions, 23,867 question-scoped sessions, and **246,750 message episodes**. A question contains 396–616 episodes (mean 493.5). Repeated contexts across questions cannot share one Graphiti partition without changing the benchmark semantics. Graphiti's `add_episode` may make several extraction, entity resolution, deduplication, date extraction, and invalidation calls for a single episode; embeddings are additional requests. Episode count is therefore not request count or token cost.

The proxy adapter does not expose reliable cost accounting by itself. In particular, `OpenAIGenericClient` 0.30.2 does not record response usage in Graphiti's `token_tracker`, and embedding tokens are not covered by that tracker. The benchmark must capture provider-side usage or wrap both chat and embedding clients before dispatch.

The staged plan is frozen without inspecting answers or scores:

1. One synthetic two-turn connectivity/schema smoke, maximum 2 episodes, under a bounded token/currency reservation recorded by the benchmark coordinator.
2. One real-session cost pilot, with no accuracy claim: the first chronological session of the first predeclared ability question, question `001be529`, session `3722ea11_2`. It contains 12 message episodes and 15,181 UTF-8 bytes. Set its reservation from the measured two-episode amplification.
3. One complete LongMemEval-S question to measure total chat calls, input/output tokens, embedding tokens, elapsed time, failures, nodes, and edges across its full 514-message history.
4. Six-question ability pilot: lexicographically first question ID in each of the six official ability strata. The IDs are emitted by the preflight before scoring.
5. Project full-run cost from observed provider usage with uncertainty bounds. Proceed beyond six only under a recorded bounded reservation. A 500-question native run is not complete and is not claimed here.

No fixed dollar estimate is defensible before the provider/model price table and measured call amplification are available. The lower bound is already large: 246,750 native message episodes, before counting multiple LLM operations per episode. A simple history-token estimate would materially understate cost.

## Local readiness

Docker CLI 29.6.2 and Compose 5.3.1 are installed, using context `desktop-linux`. At inspection time the Docker Desktop socket was absent, and the dedicated ports 17474/17687 were closed. No daemon was started and no existing service was changed.

The prepared Compose file exposes only Neo4j, binds both ports to `127.0.0.1`, uses dedicated host ports and volumes, requires an explicit password, and pins the multi-architecture image digest. It does not run the unauthenticated Graphiti graph-service container.

Docker is not required for the local pilot. `graphiti_native_neo4j.py` can prepare the official `neo4j-community-5.26.2-unix.tar.gz` (SHA-256 `95dde4f8092b9dffb57f74248ef6579bc36d6418c07ba7c513d9c95a36f44518`) under `.runtime`, configure loopback-only ports 17474/17687, disable Neo4j usage reporting, cap heap/page cache, and use the existing workspace Java 21. It manages only that installation and does not start Docker or discover/start other databases.

The local zero-call database check ran Graphiti's native `build_indices_and_constraints` against an empty isolated Neo4j. It produced 33 ONLINE indexes and zero graph nodes. Graphiti logged `EquivalentSchemaRuleAlreadyExists` for several named indexes because equivalent schema rules already existed during its setup sequence; the method continued and the final schema was online. The paid smoke checks the existing schema and does not rerun setup when all indexes are already online.

Prepared files:

- `benchmarks/graphiti-native.compose.yaml`
- `benchmarks/graphiti-native.env.example`
- `benchmarks/requirements-graphiti-native.in`
- `benchmarks/requirements-graphiti-native.txt`
- `benchmarks/graphiti_native_preflight.py`
- `benchmarks/graphiti_native_neo4j.py`
- `benchmarks/graphiti_native_smoke.py`

The CLI is intentionally zero-call. After the files are committed, run it from a clean benchmark worktree so `BenchmarkRun` records the exact source, requirements, package freeze, and prediction hash.

## Primary evidence

- [Graphiti v0.30.2 release](https://github.com/getzep/graphiti/releases/tag/v0.30.2)
- [Graphiti tagged source](https://github.com/getzep/graphiti/tree/v0.30.2)
- [Graphiti quick start](https://help.getzep.com/graphiti/getting-started/quick-start)
- [Adding episodes](https://help.getzep.com/graphiti/core-concepts/adding-episodes)
- [Neo4j configuration](https://help.getzep.com/graphiti/configuration/neo-4-j-configuration)
- [Graphiti bundled LongMemEval graph-building evaluation](https://github.com/getzep/graphiti/blob/v0.30.2/tests/evals/eval_e2e_graph_building.py)
- [Graphiti versus hosted Zep](https://help.getzep.com/zep-vs-graphiti)
- [Graphiti telemetry disclosure](https://github.com/getzep/graphiti/blob/v0.30.2/README.md#telemetry)
- [Graphiti search-filter security advisory](https://github.com/getzep/graphiti/security/advisories/GHSA-gg5m-55jj-8m5g)

## Verified native connectivity result

The separately frozen two-episode private-provider smoke completed at commit `3d5a74c` with clean source provenance: 7 chat requests and 14 embedding requests, zero uncertain requests, 10,785 reported input tokens and 5,495 output tokens. Private rates remain unknown. [Exact result artifact](graphiti-native-smoke.json).

Native ingestion recorded the sencha preference and its replacement with oolong. Search returned both edges: the old sencha edge has `invalid_at: 2026-09-12T11:00:00+00:00`, while the oolong edge remains current. This confirms lifecycle metadata is retained; default unfiltered native search also returns historical edges. It is a connectivity check, not an accuracy benchmark or a finding that Graphiti fails temporal reasoning. No OpenRouter fallback was needed for this working route.
