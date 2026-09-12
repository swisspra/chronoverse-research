# SciFact retrieval experiment

This experiment uses the official [BEIR SciFact archive](https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip), following [BEIR's direct-download example and published archive MD5](https://github.com/beir-cellar/beir). The archive provides 5,183 scientific abstracts and 300 evaluated test queries. The [BEIR dataset card](https://huggingface.co/datasets/BeIR/scifact/blob/main/README.md) lists CC-BY-SA-4.0. The underlying task is described by [Wadden et al., Fact or Fiction: Verifying Scientific Claims](https://aclanthology.org/2020.emnlp-main.609/). BEIR's retrieval test split is not a claim that the original SciFact verification leaderboard's hidden test labels were accessed.

Raw public data is downloaded into `.benchmark-data/scifact/`; it is never imported into the app's datasets. Only the corpus, queries and test qrels are extracted, through explicit ZIP member names. The official archive MD5 is verified and SHA-256 hashes are recorded for the archive and each input file. Benchmark output contains rankings and metrics, not redistributed abstracts.

## Fixed protocol

Each scientific abstract is represented by one report-plane assertion with a unique document subject and abstract object. Title plus abstract is stored as evidence text. Every comparator sees the identical string returned by the production `chronoverse.store._text` function. All assertions share one world, perspective and always-visible time interval. This controls temporal eligibility while measuring document retrieval; it does not measure scientific claim verification or temporal reasoning.

The comparators are real `rank-bm25.BM25Okapi` with its standard k1=1.5, b=0.75 and epsilon=0.25; exact cosine retrieval using the production local MiniLM embeddings; equal-weight reciprocal rank fusion of the top 1,000 BM25 and dense results with k=60; and the actual production `Store.query` implementation. BM25 and Chronoverse use the same production Unicode tokenization, without stemming or stop-word removal. Ties use document IDs. Parameters are fixed before examining test judgments; no qrels are used for parameter or document selection.

SciFact has no imported graph of scientific entities. The assertion graph contains document-to-abstract links. This means its graph support can amount to a constant relevance bonus; the experiment does not demonstrate the benefit of an extracted scientific entity graph.

## Cache and timing distinction

The stock application uses an LRU embedding cache of 2,048 entries, smaller than the corpus. Two unmodified `Store.query` pilot calls over the full corpus measure real application behavior and report cache hits/misses. The first includes model initialization; the second can still re-encode the entire corpus because sequential access evicts entries before reuse. Two samples are insufficient for a stable latency percentile estimate.

The full accuracy experiment retains `Store.query`, filters, lexical scoring, semantic scoring, graph support, score rounding and ranking unchanged. Only within the isolated benchmark process, document embeddings use an unbounded memoization wrapper around the exact original embedding function. Query embeddings are always computed fresh. This configuration is labeled **Chronoverse Store — benchmark-only document cache**. It is not stock application performance, and no production file is changed. Top-10 IDs and scores are compared exactly against the stock pilot outputs.

Document embeddings are computed once using the original single-document embedding function. The same vectors feed exact dense retrieval. Warm query latency includes uncached query encoding for both dense methods. RRF latency includes its BM25 and dense retrieval plus fusion. Corpus indexing and model embedding time are reported separately. The methods run sequentially on one machine; other local workloads can affect timing. Hardware/runtime versions are recorded, and readers should rerun on an idle deployment target before drawing capacity conclusions.

## Reproduce

```bash
uv venv .bench-venv --python 3.12
uv pip install --python .bench-venv/bin/python -e 'backend[semantic]' rank-bm25 pytest
.bench-venv/bin/python -m pytest benchmarks/tests -q
.bench-venv/bin/python -m benchmarks.scifact
```

The model cache must already exist from the normal local setup; model inference loads cached weights only. No document or query text goes to an external embedding or LLM provider.

The output is `docs/benchmarks/scifact-results.json`, with separate method run files and a stock-pilot file. nDCG@10, Recall@5/10, MRR@10 and hit@1 are macro-averaged across all 300 test queries. Missing results count as zero. These figures are not directly comparable with an official leaderboard run using different models or preprocessing.
