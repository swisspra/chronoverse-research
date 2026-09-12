# Hosted model transport audit

The user supplied a private OpenAI-compatible endpoint and runtime credential. Neither is part of this repository. The model list was checked again after embedding and reranking aliases were added. This is a transport audit, not a model-quality ranking.

| Requested alias | Observed behavior | Benchmark treatment |
| --- | --- | --- |
| `text-embedding-3-large` | Embedding requests succeed; returned identity matches; 3,072 dimensions | Scored as a separately labelled hosted retrieval extension |
| `Cohere-rerank-v3-5` | `/rerank` returns HTTP500, reporting `Unsupported provider: azure`; chat fallbacks are also unsupported for reranking | No rerank score; retain the local cross-encoder control |
| `claude-sonnet-5`, `gpt-5.6-terra`, `Claude Haiku 4.5` | Earlier probes returned `response.model: gemini-3-flash-preview` | Historical routing discrepancy; these aliases are not used for the pilot |
| `vertex_ai/gemini-3.8-flash` | Latest direct probe returns the exact requested identity, `finish_reason: stop`, and `OK`; 5 total reported tokens | Selected for every answer-pilot arm, with returned identity pinned |

A listed alias establishes neither a working route nor the identity of its upstream weights. The answer harness records both requested and returned identities, pins one returned identity across arms, and stops on an identity change. The reference-authoring record likewise discloses the actual returned identity and subsequent human/parent-agent corrections.

The rerank error is consistent with an Azure provider-prefix mismatch. The official [LiteLLM Azure AI rerank documentation](https://docs.litellm.ai/docs/providers/azure_ai#rerank-endpoint) uses `azure_ai/cohere-rerank-v3.5`; the endpoint owner should configure the corresponding Azure AI deployment and remove chat-model fallbacks from this rerank route. This is a proposed configuration correction, not a remotely applied or verified fix.

Embedding batches are cached by exact input, model and endpoint hash. All completed usage remains in accounting, including requests made before an input-handling repair. One failed FiQA batch containing empty source text remains reserved and unresolved; its charge is unknown. The repaired payload excludes empty strings and preserves their corpus rows as non-ranking zero-vector sentinels. It is a different request, not an automatic retry of the unresolved batch.

No proxy prices or invoice were supplied. Dollar cost is unknown. Token reservations are conservative client-side controls, not a dollar guarantee or proof that the provider honors a limit. Batch API support is unverified. The direct Gemini route now passes its bounded transport probe. The private reranker still returns the same HTTP500 on recheck; the separate OpenRouter experiment below completed.


## OpenRouter fallback supplied by the user

After the private rerank route continued to return HTTP500, the user authorized OpenRouter for missing or broken routes. A two-document request to `/api/v1/rerank` using `cohere/rerank-v3.5` succeeded, returned `model: rerank-v3.5`, both unique document indices and finite relevance scores. Reported usage was one search unit and USD0.001. This is a successful transport probe, not a benchmark score.

OpenRouter lists `google/gemini-3.8-flash` at USD0.75 per million input tokens and USD3.75 per million output tokens, and `openai/text-embedding-3-large` at USD0.13 per million input tokens at inspection time. These are OpenRouter's advertised rates, not verified prices for the private proxy. See the [models API](https://openrouter.ai/api/v1/models), [embedding models API](https://openrouter.ai/api/v1/embeddings/models), and [rerank API documentation](https://openrouter.ai/docs/api/api-reference/rerank/submit-a-rerank-request).

The current answer pilot retains its original working provider and pinned identity. A provider change creates a separately attributed run. Embedding caches include endpoint identity; vectors are not spliced across providers under a shared alias. Credentials remain outside version control.

The full fixed-pool SciFact rerank comparison completed with 300 successful native requests and USD0.300 reported usage. Its independently verified nDCG@10 is 0.773748, versus 0.688634 for the original local cross-encoder. [Result, paired intervals and length confound](OPENROUTER-RERANK-RESULTS.md).
