# Optional hosted embedding experiment

No paid API calls were made in round 2. Local experiments use public benchmark corpora and downloaded model weights. User documents remain on this machine.

## Concrete next experiment

Compare Voyage `voyage-4-large` with the best local configuration on the same full SciFact, NFCorpus and FiQA splits. Send only those public titles, abstracts/passages and benchmark query texts. Preserve test judgments locally. No uploaded profile documents, ledger history or source credentials are included. Use document/query input types, store returned vectors once, and retain exact model/tokenization settings.

The published standard embedding rate observed on 2026-09-12 is **$0.12 per million tokens**. An illustrative 10 million input tokens costs $1.20; 50 million costs $6.00. These are arithmetic examples, not a measured token bill. A proposed **$5 hard budget** needs a provider-token count before dispatch and an application-side stop before crossing the cap. Free allocations are not assumed available. Indexing is charged once per corpus/model; queries add token usage.

Source: [Voyage pricing](https://docs.voyageai.com/docs/pricing), [embedding API/model instructions](https://docs.voyageai.com/docs/embeddings). Availability, account allowance and current rates must be rechecked when enabling the run. A configured API key and approval of the concrete public-data scope/budget are still needed. No credentials were searched or changed for this proposal.

OpenAI embeddings and Azure-hosted embeddings remain alternatives, but their exact current model pricing was not reliably extractable from the official pages in this run. No stale price is used in a cost comparison. Provider price is not evidence of quality; the hosted model must pass the same evaluation.
