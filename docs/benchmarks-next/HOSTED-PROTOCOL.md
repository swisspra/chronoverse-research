# Hosted retrieval amendment, before scoring

The user added an embedding model and reranker to their OpenAI-compatible proxy after the local comparison was frozen. This is a separately labelled extension; it does not replace any local baseline or alter application defaults.

Evaluate proxy-advertised `text-embedding-3-large` using its full 3,072 dimensions, exact normalized dot-product retrieval and title plus newline plus passage. Cap each input at 512 `cl100k_base` tokens, record corpus-specific truncation, and retain top 100 with document-ID tie-breaking and self-document exclusion. Report linear-gain nDCG@10 on all official TEST queries, starting with SciFact and then NFCorpus/FiQA if the authorized token reservation permits. Compare against already frozen local results descriptively; tokenizer differences and unversioned hosted aliases prevent a claim of identical text exposure or immutable model weights.

Prediction: hosted dense retrieval may improve semantic ranking, but a stronger embedding alone cannot restore a claim removed before ranking by an undelivered lifecycle event. A negative ranking result is retained. No threshold is tuned using qrels.

The supplied reranker alias is tested separately for transport support before any scored comparison. A model list entry alone does not establish a working rerank route. If the proxy returns an upstream routing error, publish that blocker and retain the local cross-encoder control. Never substitute chat generation for a reranker silently.

Runtime endpoint and key remain outside the repository. Cache each exact request by endpoint hash, model and input text; retain every completed vector hash and API token usage. Reserve a conservative UTF-8 byte bound before dispatch; pending or failed calls cannot silently retry. A fixed token cap is not a dollar guarantee when proxy prices are unavailable. No billing cost is invented. Batch API availability is unverified on this custom proxy; embedding batches contain at most 64 inputs. The user explicitly authorized using available models; all document inputs in this extension are public benchmark corpora.

## Empty-document repair, before any FiQA score

The first FiQA API pass returned HTTP400 for a batch containing an empty source. The corpus has38 empty title/text rows. Preserve their corpus IDs/count but send no empty string to the embedding API: use an explicit zero-vector sentinel and exclude these contentless rows from ranking. This matches the lexical engine's empty-document omission as an input-handling policy; no qrel grade informs it. Failed dispatch reservations remain in accounting. Existing SciFact/NFCorpus result bytes and source commit are archived before rerunning those cells from cached vectors. Nonempty text preprocessing and ranking parameters are unchanged. Record empty counts and require response.model to match the requested embedding model on every new batch.

## Explicit timeout recovery, before the first FiQA score

A later FiQA batch timed out after 120 seconds. Completed batches remain immutable in the exact-input cache. The timeout's charge is unknown, so its entire reservation remains counted. The runner now permits one explicitly selected timeout signature to receive one additional attempt, reserving the full additional amount under the same total cap before dispatch. It retains the prior attempt and its error in that request's accounting. This is an operator-selected recovery, not an implicit network retry; HTTP400 batches and repeated recovery attempts remain refused. A second failure stops the run again. This operational amendment changes no input text, model, vector normalization, ranking, qrels or scoring rule.
