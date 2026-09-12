# What this round can establish

1. **Systems hypothesis:** storing exact document vectors across queries and restarts removes repeated inference without changing temporal snapshots or rankings. Test above 2,048 records, compare IDs/available scores, and report cold build separately from warm/reopened queries.
2. **Retrieval hypothesis:** model choice, lexical retrieval and reranking affect relevance independently of temporal semantics. Use complete public datasets in scientific evidence, biomedical/nutrition search and finance. Same text, fixed model instructions, no test-label weight/threshold selection. Report per-domain wins and losses instead of selecting a favorable aggregate.
3. **Temporal hypothesis:** explicit valid time, known time and lifecycle metadata prevent invalid context. Compare against conventional retrieval supplied the same metadata and an independent filter. Include late evidence, boundaries, conflicting values, paraphrases and empty answers. A capable filtered baseline tying Chronoverse is evidence that the semantics can be implemented, not a unique graph-reasoning advantage.
4. **Abstention hypothesis:** a development-fitted gate can reduce unsupported retrieval while retaining relevant evidence on held-out entities/scenarios. Report missed relevant answers and precision/coverage tradeoffs, not only correct empty answers. Freeze the selected rule before test scoring. Keep this gate experimental until tested on representative user documents.

## Interpretation boundaries

These are retrieval-context experiments without an LLM answerer. Scientific relevance does not establish factual truth. Synthetic gold is intentionally designed and must not be described as a public temporal benchmark. Model training may include public benchmark material; we cannot rule out pretraining overlap. No result proves universal superiority or the entire Chronoverse theory.

## Architecture choices

SQLite derived vectors suit this local single-user application and keep profile files self-contained. Redis can later share cached objects between workers, but does not by itself supply semantic nearest-neighbor indexing or resolve knowledge-time correctness. Exact scoring retains the correctness baseline; consider HNSW/FAISS or pgvector only after measuring candidate search as the bottleneck, and measure recall lost to approximation.

A new embedding model cannot simply inherit MiniLM's absolute 0.28 threshold. BGE's model card describes a different score distribution. Treat model score calibration as part of a retrieval strategy and validate it separately. A cross-encoder can rerank eligible candidates, but cannot rescue evidence absent from its candidate pool or supply factual verification.

Sources: [BGE model card](https://huggingface.co/BAAI/bge-small-en-v1.5), [BEIR datasets](https://github.com/beir-cellar/beir/wiki/Datasets-available), [MS MARCO cross-encoder](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2).
