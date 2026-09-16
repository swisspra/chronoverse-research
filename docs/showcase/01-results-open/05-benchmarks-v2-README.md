# Chronoverse: experiment round two

> **STATUS · CURRENT** — original dated 2026-09-13 00:53 · chain and replacements in [`00-START-HERE/VERSION-MAP.md`](../00-START-HERE/VERSION-MAP.md)

## Next-round baseline correction

The [v3 matched-length comparison](../benchmarks-v3/README.md) strengthens the lexical baseline and measures both models at 256 and 512 tokens. Historical result bytes below are unchanged.

| Dataset | Historical BM25 | Strong Pyserini BM25 | Historical BGE@512 | Strong BM25 + BGE@512 |
| --- | ---: | ---: | ---: | ---: |
| SciFact | 0.6519 | 0.6647 | 0.7127 | 0.7118 |
| NFCorpus | 0.3064 | 0.3254 | 0.3438 | 0.3593 |
| FiQA | 0.2167 | 0.2361 | 0.4035 | 0.3627 |

The FiQA hybrid loss persists with strong BM25 and at both matched lengths, but shrinks from the historical 0.0743 to 0.0408 at 512 tokens. The v3 report contains the paired, multiplicity-adjusted inference; these cross-round rows are descriptive. Three-way fusion improves numerically in v3, and length changes do not universally help either model.


Open the [interactive report](index.html). This round separates production performance work from retrieval-model experiments and temporal correctness. All inference in the recorded experiments runs locally. No uploaded user documents or paid APIs are used.

## What changed in the application

Document vectors now persist in each profile's SQLite database. The derived index identifies the embedding model and exact knowledge-visible text, validates stored vectors, and rebuilds missing or corrupt entries. Querying a historical snapshot cannot reuse a vector made from evidence that had not yet been recorded. Document inference is batched and scoring retains the existing exact cosine calculation. This removes the previous 2,048-entry document-cache eviction problem without changing ranking weights or the default model.

The scope projection normalizes clocks once and fetches lifecycle events in one scoped query, avoiding one database lookup for every eligible assertion. This preserves event order, half-open intervals, and historical evidence visibility. The append-only assertion/event ledger remains authoritative; derived indexes are disposable.

A Store-owned lexical postings cache now reuses unique-token positions for an exact ordered cohort of projected texts. It rebuilds on text or ordering changes, retains at most 64 MiB of cache objects per Store, and falls back to direct tokenization when a cohort exceeds the cap. This cap excludes caller-owned text and temporary tokenizer/result objects; it is not a process RSS limit.

Redis is not needed for this single-process local deployment. An additional shared cache would add invalidation and operational work. Profile-local persistence addresses repeated embedding; profiling identifies lexical tokenization and projection as the next costs. Approximate vector search is deferred until exact candidate scoring is a measured bottleneck.

To prewarm all currently eligible assertions in an existing profile:

```bash
backend/.venv/bin/python scripts/prewarm_profile.py --profile demo
```

Use `--valid-at` and `--known-at` to prewarm a specific historical view. This creates derived vectors, not facts or lifecycle events. The first build can take appreciable time for large profiles.

## Production index: correctness first

Full SciFact: **5,183 documents, 300 test queries**. The production `Store.query` is called directly, with no benchmark monkeypatch or unbounded document-vector cache.

- All 300 top-10 ID lists match the earlier v1 run. Both score lists available from v1 also match.
- All 300 fresh/reopened top-10 ID lists and rounded scores match exactly.
- nDCG@10 remains **0.691969**; Recall@10 remains **0.816056**.
- Fresh lazy initialization and document encoding took **946.19 s** under concurrent load. A new process reopened the stored index and answered its first query in **2.144 s**, with the vector count unchanged at 5,183.
- Warm p50 was **1.422 s** in the fresh process and **1.572 s** after reopening. Every distinct test query was freshly encoded; neither pass had query-embedding cache hits.

These timings are observations on a shared machine, not controlled speedup estimates. The earlier v1 benchmark-only unbounded cache had different memory and workload conditions. Separate cold indexing from warm retrieval and model loading. [Raw results](index-results.json), [protocol](INDEX-PROTOCOL.md), [stage profiling](index-stage-timing.json).

## Measured follow-up optimizations

Both follow-up production runs reused the same 5,183 persisted vectors and separately checked all 300 top-10 ID lists and rounded scores against the original index run. Every list and score matched; each run recorded zero query-embedding cache hits.

| Recorded production stage | Warm p50 | Warm p95 | nDCG@10 |
| --- | ---: | ---: | ---: |
| Persistent index, reopened process | 1.572 s | 2.043 s | 0.691969 |
| Clock normalization + bulk event loading | 0.928 s | 2.394 s | 0.691969 |
| Plus bounded lexical postings | **0.800 s** | **1.492 s** | **0.691969** |

These runs occurred at different times under changing shared-machine load. They do not isolate a causal end-to-end speedup. The controlled equality checks establish preserved output; the timings establish observed performance for the recorded runs.

The separate component pilot checked every lexical score: **1,554,900 document/query pairs**, all exactly equal. Hash-inclusive postings p50 was 5.09 ms versus 155.14 ms for retokenization; this excludes the rest of the request. Production retained **9,412,564 bytes (8.98 MiB)** for the tested cohort, below its 64 MiB per-Store cache limit. An over-budget cohort falls back to the original calculation.

Artifacts: [projection run](optimization-results.json), [lexical production run](lexical-optimization-results.json), [component pilot](token-postings-pilot.json), [projection protocol](OPTIMIZATION-PROTOCOL.md), [lexical protocol](LEXICAL-PROTOCOL.md).

## Cross-domain retrieval

The full comparison covers scientific evidence (SciFact), biomedical/nutrition retrieval (NFCorpus), and financial questions (FiQA): 66,454 documents and 1,271 test queries. All three corpora and all test queries completed. A second scoring implementation in this repository reproduced every reported aggregate metric from the official judgments and saved ranking IDs; all 12 vector-array hashes and unit norms also passed verification.

nDCG@10 (higher is better):

| Fixed system | SciFact | NFCorpus | FiQA |
| --- | ---: | ---: | ---: |
| BM25 | 0.6519 | 0.3064 | 0.2167 |
| MiniLM dense | 0.6451 | 0.3167 | 0.3687 |
| BGE dense | 0.7127 | 0.3438 | 0.4035 |
| BM25 + MiniLM RRF | 0.6816 | 0.3347 | 0.3366 |
| BM25 + BGE RRF | 0.7043 | 0.3446 | 0.3292 |
| BM25 + MiniLM + BGE RRF | 0.7110 | 0.3567 | 0.3821 |

BGE dense has the highest observed score on SciFact and FiQA; three-way RRF has the highest on NFCorpus. **Adding BM25 does not always help:** on FiQA, BGE dense scores 0.4035 while BM25 + BGE falls to 0.3292. Fusion needs domain-specific validation rather than unconditional deployment.

Against the predeclared MiniLM-hybrid reference, BGE dense has paired nDCG differences +0.0311 [0.0020, 0.0604] on SciFact and +0.0669 [0.0465, 0.0872] on FiQA. Three-way RRF improves NFCorpus by +0.0220 [0.0125, 0.0317]. These are query-bootstrap 95% intervals, without a multiple-comparison adjustment; observed winners are descriptive choices from this experiment, not guarantees for a new domain. [Complete results, predictions and intervals](cross-domain-results.json).

The fixed systems are BM25, MiniLM, BGE-small English, the two model-specific BM25 hybrids, and three-way reciprocal rank fusion. RRF uses k=60 and top-100 inputs. BGE receives its published query instruction exactly once; documents receive no query prefix. Models use local FP32 inference through Apple MPS. No labels select weights or prompt settings.

This track uses title plus passage text, unlike the assertion-wrapped text in the index and reranker tracks. Its scores are not a direct before/after comparison with those tracks. Reported dense query ranking latency uses precomputed query vectors and is not end-to-end request latency. Public benchmark overlap with model training cannot be ruled out. English results do not establish Thai quality.

For graded NFCorpus relevance, nDCG uses linear relevance gains compatible with `trec_eval`; SciFact/FiQA labels are binary. Query/document ID self-matches are excluded as in BEIR evaluation. Ties are resolved deterministically. Sources: [BEIR datasets](https://github.com/beir-cellar/beir/wiki/Datasets-available), [trec_eval nDCG](https://raw.githubusercontent.com/usnistgov/trec_eval/master/m_ndcg_cut.c), [BGE model card](https://huggingface.co/BAAI/bge-small-en-v1.5).

## Reranking: measured gain is uncertain

All 300 SciFact queries retrieve a fixed top-50 BM25/MiniLM RRF pool, then score those 15,000 query/passage pairs with the local `cross-encoder/ms-marco-MiniLM-L6-v2` model. The original model runs in FP32 on MPS, maximum sequence length 512, batch size 16. First-stage nDCG exactly reproduces v1 RRF.

| System | nDCG@10 | Recall@10 | Hit@1 | Pipeline p50 |
| --- | ---: | ---: | ---: | ---: |
| BM25 + MiniLM RRF | 0.673366 | 0.815056 | 0.533333 | 0.173 s |
| Same candidates + cross-encoder | 0.688634 | 0.825556 | 0.563333 | 3.119 s |

The paired mean nDCG change is **+0.015268**, with a 95% bootstrap interval **[-0.013802, +0.044060]**. The interval includes zero. Individual failures and gains are inspectable in the report. The reranker is **experimental**, not the application default. It adds latency and cannot recover evidence missing from the first-stage pool.

CPU FP32/INT8 attempts were stopped after timing pilots. Their partial artifacts are retained for transparency and are not full accuracy comparisons. [Complete reranker results](rerank-results.json), [model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2).

## Harder temporal cases and abstention

The frozen synthetic fixture contains **206 assertions and 38 lifecycle events**. DEV has 40 questions; TEST has 114 questions with disjoint entity names and scenario families. TEST includes 72 answerable and 42 empty-answer questions. It covers paraphrases, competing predicates, similar entity names, chained changes, late evidence, interval boundaries, and conflicts. Gold support IDs are manually specified.

A predeclared absolute-cosine/relative-margin grid is selected on DEV under an answerable-coverage constraint, then frozen for TEST. All four systems select cosine 0.60 and margin 0.05. Adding this gate to BM25 introduces a dense semantic signal; that condition is an engineered baseline, not native BM25.

| Actual Store, held-out TEST | Ungated | Frozen DEV gate |
| --- | ---: | ---: |
| Micro precision | 0.0730 | 0.6486 |
| Micro recall | 1.0000 | 0.9231 |
| nDCG@10 | 0.9363 | 0.8772 |
| Correct abstention on empty targets | 0/42 | 36/42 |
| False abstention on answerable targets | 0/72 | 4/72 |

Higher precision costs relevant evidence. Moreover, gated BM25 reaches precision **0.6990**, and ungated filtered RRF reaches nDCG **0.9619**, both beating Store on those respective measures. Preserve these losses when interpreting the architecture. The gate remains experimental until calibrated on representative user documents.

This is a designed diagnostic, not an independently authored public temporal benchmark. Shared vocabulary/authoring patterns remain despite the split. It does not contain an explicit multi-hop evaluation, and cannot establish a unique GraphRAG advantage. [Results and all predictions](temporal-results.json), [frozen fixture](temporal-fixture.json).

## What the theory still needs

Temporal metadata demonstrably controls which evidence is available and applicable. A capable conventional retriever supplied the same metadata can also implement those filters. A relevance improvement from a new model or reranker is separate evidence from a graph/time reasoning improvement.

The next decisive test is a controlled graph/time ablation using independently authored multi-hop questions, fixed models and candidate budgets, and explicit support/answer judgments. MultiTQ and MusTQ are researched candidates; neither was run here. Knowledge time and late corrections need additional ground truth beyond ordinary temporal KG facts. See [architecture and next experiments](NEXT-ARCHITECTURE.md).

A hosted multilingual embedding comparison is a concrete optional follow-up. [API options](API-OPTIONS.md) specifies public-data scope, published pricing, and a proposed budget; no API experiment is claimed.

## Verification

The final application passed 77 backend tests and 579 benchmark tests. Live HTTP/MCP searches and existing profile counts were checked after restart. All aggregate retrieval metrics were recomputed by a second implementation in this repository; the browser report passed dataset/toggle/link and mobile layout checks. See [verification evidence](VERIFICATION.md) and [machine-readable audit](verification-results.json).

## Reproduce

Run commands from the repository root with the isolated environments used by each experiment. Result JSON records model/runtime fingerprints and source hashes; [the executed cross-domain source and unamended result](source/cross-domain/) preserve provenance for a later descriptive-only MPS metadata correction; use matching artifacts when comparing outputs. Large model/dataset downloads and complete runs require time and disk space. Frozen package inventories are saved for the [app](requirements-app-frozen.txt), [index experiments](requirements-index-frozen.txt), and [MPS experiments](requirements-mps-frozen.txt); the editable backend path is relative to this repository root.

```bash
# Production exact index experiment: creates isolated benchmark data.
.bench-venv/bin/python -m benchmarks.index_scifact

# Hard temporal fixture and DEV-frozen gate.
.bench-venv/bin/python -m benchmarks.temporal_v2

# Download/verify public archives, then run the full three-domain comparison.
.bench-mps-venv/bin/python -m benchmarks.download_cross_domain
.bench-mps-venv/bin/python benchmarks/cross_domain.py --datasets scifact,nfcorpus,fiqa --top-k 100 --backend mps-fp32

# Full fixed-pool reranker comparison.
.bench-mps-venv/bin/python -m benchmarks.rerank_v2 --runtime mps

# Rebuild compact standalone HTML from completed result files.
.bench-venv/bin/python -m benchmarks.render_report_v2

# Serve both round-two and earlier reports.
python3 -m http.server 8003 --bind 127.0.0.1 --directory docs
```

The model experiments perform retrieval evaluation without generating answers or using an LLM judge. Relevance labels are not truth labels. No experiment in this report proves universal superiority or the entire Chronoverse theory.


[User-provided external review](../EXTERNAL-REVIEW.md) reports a separate recomputation of listed figures. This repository has not authenticated the reviewer identity or replayed that external execution.
