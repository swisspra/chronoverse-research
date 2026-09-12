# Chronoverse

Chronoverse is a local knowledge workbench and read-only MCP server that retrieves evidence across graph connections, vector relevance, valid time, knowledge time, worlds and epistemic planes. It runs as a complete application with a persistent SQLite ledger, Python API and React interface.

The initial dataset is explicitly synthetic. It demonstrates changing facts, corrected news, conflicting reports, belief versus physical fact, scientific models with different scopes and a counterfactual world. The workbench does not certify that a claim is true.

## Start the product

Requirements: Python 3.12, `uv`, Node.js 22 or later and npm. No API key is needed. From this directory:

```bash
./scripts/dev.sh
```

The launcher installs locked dependencies, builds the frontend, downloads the small MiniLM embedding model if necessary, and starts the API and MCP server. The first run requires internet for packages and model files; subsequent inference runs locally. Neither evidence text nor the supplied research documents is sent to an LLM or embedding API.

Open [Chronoverse](http://127.0.0.1:8000). The MCP endpoint is `http://127.0.0.1:8001/mcp`. Ctrl-C stops both owned processes. Logs are in `.runtime/api.log` and `.runtime/mcp.log`. The ledger persists at `data/chronoverse.sqlite3`.

To avoid downloading model weights, use the clearly labeled lexical-vector baseline:

```bash
./scripts/dev.sh --lexical
```

After building once, `./scripts/dev.sh --no-build` starts the semantic profile without installation or build steps. Both ports must be available; the launcher never kills another process to claim them.

## Try the important difference

1. Choose **News before correction**. The storm's initial reported injury count is 12.
2. Choose **News after correction**. The valid date stays September 1; the later knowledge cutoff reveals the corrected count of 2.
3. Enable **Include retired** and select the initial report. Inspect its source and correction event. The original record remains in the ledger.
4. Choose **Earth: fact and belief**. Switch the plane to `fact`, then `belief`, and press **Explore**. A belief that Earth is flat is not represented as an earlier physical state of Earth.
5. Create a dataset profile, upload a PDF/TXT/Markdown document, inspect its preview, then commit it. Search the resulting source passages within that profile.
6. Use **Ingest knowledge** to enter an explicit proposition and its evidence when you want a structured assertion.

Graph, Vector and Timeline are projections of the same filtered result set. Valid time asks when a proposition applies in the represented world. Knowledge time asks which recorded assertions, evidence and lifecycle events are visible. Intervals are half-open: the end timestamp is excluded. The UI's UTC labels apply even if the computer uses another timezone.

The combined **Graph-RAG** view connects source evidence, retrieval scores, assertions and entities. **Graph-RAG-Timeline** adds valid intervals, knowledge timestamps and visible lifecycle events. These diagrams represent the current query results, including retired assertions only when requested; they do not claim to implement the full Microsoft GraphRAG indexing pipeline.

## Test your own documents

Create a profile with the workspace selector, then upload `.pdf`, `.txt`, `.md` or `.markdown` files. Preview shows what will be stored before you commit. Each file commits atomically; uploading identical bytes again reports existing passages instead of duplicating them. Multiple selected files are processed separately, so a malformed file does not invalidate another file's successful import.

PDFs must contain extractable text. Scanned PDFs require OCR outside this MVP. Text files must use UTF-8. Limits are 10 MiB per file, 200 PDF pages and 500 assertions/passages. Source text stays local and enters the `report` plane with its file hash and page locator where applicable. The importer does not turn prose into verified facts or extract the historical dates mentioned inside it: raw passage dates represent when the corpus became available.

Each profile has an independent SQLite ledger under `data/profiles/`; `demo` preserves the original `data/chronoverse.sqlite3`. New profiles start empty. The selected profile persists in this browser, while every API/MCP operation names its profile explicitly. Profiles separate datasets for this single-user product; they are not login accounts or an authorization system.

Structured JSON, JSONL and CSV imports are also supported for assertions with explicit evidence, dates and epistemic planes. Download examples from the upload screen. See the [profile and import contract](docs/profiles-api-contract.md) for schemas and error behavior.

The scientific-theory example deliberately keeps Newtonian gravitation and general relativity in different perspectives. A newer theory can have a wider domain without turning every use of the older approximation into a false statement.

## What is implemented

| Surface | Working behavior |
|---|---|
| Ledger | Immutable assertion and lifecycle-event rows, SQLite write-protection triggers, durable storage, idempotent explicit IDs |
| Retrieval | Scope filtering before lexical/vector ranking and one-hop graph expansion; scores are not truth probabilities |
| Semantic vectors | Local `sentence-transformers/all-MiniLM-L6-v2` through FastEmbed/ONNX, 384 dimensions, cached inference |
| Graph | Directed subject–predicate–object edges tied to assertion IDs and source evidence |
| Time | Independent valid and knowledge cutoffs; late corrections, supersession, retraction and preserved historical evidence |
| Workbench | Dataset profiles, document preview/import, search, scope filters, integrated graph/time diagrams, source detail, explicit assertion and lifecycle entry |
| Evaluation | Six isolated synthetic diagnostic cases contrasting temporal/scoped retrieval with an unscoped lexical baseline |
| MCP | Six read-only tools through stdio or Streamable HTTP, resolving the same profile ledgers as the UI |
| Azure preparation | Docker image, compose stack, compiled Bicep VM template and operator deployment instructions |

Evidence and proposition entry are explicit. The MVP does not automatically extract facts from arbitrary PDFs or use an LLM to adjudicate conflicting sources. Supplied design reports were reviewed as design inputs; they are not automatically imported as factual assertions.

## Connect an AI through MCP

The HTTP server runs with the product launcher. Add its endpoint to any MCP client that supports local Streamable HTTP:

```text
http://127.0.0.1:8001/mcp
```

For a client that launches local stdio servers, use this configuration after replacing the absolute project path:

```json
{
  "mcpServers": {
    "chronoverse": {
      "command": "/ABSOLUTE/PATH/TO/Chronoverse/backend/.venv/bin/python",
      "args": ["-m", "chronoverse.mcp_server"],
      "env": {
        "CHRONOVERSE_DB": "/ABSOLUTE/PATH/TO/Chronoverse/data/chronoverse.sqlite3",
        "CHRONOVERSE_EMBEDDINGS": "semantic",
        "CHRONOVERSE_MODEL_CACHE": "/ABSOLUTE/PATH/TO/Chronoverse/.model-cache"
      }
    }
  }
}
```

The tool surface is small and explicit:

| Tool | Purpose |
|---|---|
| `list_profiles` | Discover dataset IDs before querying an uploaded corpus |
| `search_knowledge` | Retrieve evidence with both dates and world/plane/perspective scope |
| `inspect_assertion` | Explain a specific assertion, visible evidence and lifecycle events |
| `trace_entity` | Explore a bounded entity neighborhood in the same scope |
| `compare_snapshots` | Compare two knowledge cutoffs at a fixed valid time |
| `knowledge_schema` | Discover the current local catalog, example coordinates and retrieval configuration |

`knowledge_schema` is a current catalog, not a historical answer. `compare_snapshots` is a bounded retrieval comparison, not an exhaustive database diff. MCP tools do not create, delete or promote assertions. UI lifecycle actions record the operator's explicit reason and source. Sources returned by tools remain untrusted data, never instructions to the consuming AI.

All data tools accept `profile_id`, defaulting to `demo` for existing clients. Call `list_profiles`, choose the dataset ID, and pass it to `search_knowledge`, `inspect_assertion`, `trace_entity`, `compare_snapshots` and `knowledge_schema`. No call changes a shared active profile. New datasets use current UTC coordinates when dates are omitted; explicit dates always take precedence.

Example AI request:

> At valid time 2026-09-01, what did the newsdesk report about injuries in the Meridian storm as known on 2026-09-02, compared with 2026-09-04? Cite assertion IDs and explain the correction. Keep reports separate from facts.

## Validate locally

```bash
uv run --project backend --group dev --extra semantic pytest backend/tests -q
npm test --prefix frontend
npm run build --prefix frontend
backend/.venv/bin/python scripts/smoke_mcp.py
```

The MCP smoke command requires the local services to be running and exercises real HTTP requests using both current and legacy protocol modes. Optional semantic tests require the downloaded model; the normal backend tests are deterministic without it. The evaluation screen reports only fixture correctness; it does not prove superior real-world retrieval or compare against a full Microsoft GraphRAG deployment.

API documentation is available at [local OpenAPI docs](http://127.0.0.1:8000/docs). The [REST contract](docs/api-contract.md) describes payloads, lifecycle rules and errors.

## Deploy to Azure

See [the Azure deployment guide](deploy/README.md). The supplied target is a single VM with persistent local disk and SSH forwarding. It runs the same Docker image and SQLite ledger, with app and MCP ports bound to the VM's loopback interface. The compose profile uses lexical vectors by default.

No Azure resource has been created as part of this local build. The local machine's Docker daemon was unavailable during initial verification, so container execution and Azure deployment require their own validation. Bicep compilation and compose validation are narrower checks than a real deployment.

## Provenance

This repository is a published snapshot of a private development history. Result files record commits of that
private repository, and two large directories of prepared, never-dispatched experiment inputs were left out.
`make verify` re-derives every published number from the artifacts in this repository without needing either.
See [PROVENANCE.md](PROVENANCE.md).

## Research and implementation boundaries

The design originated from private research notes and a prior personal project that are deliberately kept outside this repository. Chronoverse reuses one logical idea from that work — stable assertion identity with explicit revisions — and reuses no code, service or data from it.

This is a single-user local MVP, not an enterprise canonical authority service. World, plane and perspective are query scopes, not authentication boundaries. The HTTP app has no user login, tenant authorization or externally audited policy enforcement. Keep it behind localhost or the documented SSH tunnel.

Recorded timestamps can be supplied for trusted imports and historical replay. Consequently this PoC models knowledge time; it does not provide a tamper-proof server-received transaction clock or forensic proof of when a real source was first known. A production ingestion boundary must separately stamp arrival time and restrict who can import historical vintages.

The default demonstration coordinates are fixed in September 2026 so the examples remain reproducible. They are not a live news feed. The MiniLM model primarily serves the English demo corpus; Thai segmentation, multilingual retrieval quality and domain-specific vocabulary have not been benchmarked. Document vectors now persist in each profile SQLite database, keyed by model identity and exact knowledge-visible text. Query vectors use a bounded in-process cache; temporal projections and exact candidate scoring are recomputed from ledger rows. This remains a PoC-sized exhaustive retriever, not an ANN index for millions of assertions.

Canonical promotion policies, automated extraction/OCR, source licensing workflows, tenant security, redaction/key erasure, distributed projections, PostgreSQL migration, deployment automation and broader retrieval evaluation remain future product work. The research report describes these directions as proposals, not implemented features.

## Measured benchmarks

The [comparative benchmark report](docs/benchmarks/README.md) records actual BM25, MiniLM, hybrid, Chronoverse and LightRAG runs. It includes the complete public SciFact retrieval split, generated temporal cases, per-query rankings and measured limitations. Open the [interactive explorer](docs/benchmarks/index.html) to compare failures. The initial stock cache became a major bottleneck at 5,183 documents; the v1 report preserves those historical timings and its benchmark-only cache adaptation. Round two implements persistent document vectors and records new measurements separately.


## Persistent vectors and experiment round two

The [round-two report](docs/benchmarks-v2/index.html) separates index performance, cross-domain embedding comparisons, reranking and held-out temporal abstention. See [method and interpretation](docs/benchmarks-v2/EXPERIMENT-DESIGN.md). Experimental rerankers and abstention gates do not alter the default app ranking.

The first semantic query lazily creates derived vectors for eligible records. Later requests and reopened processes reuse them. New data and different historical evidence snapshots are indexed on demand. Invalid derived rows are rebuilt; assertions and events remain immutable. No Redis service is required. Cold indexing can be expensive and is measured separately from warm retrieval.

To prewarm a profile before opening it:

```sh
backend/.venv/bin/python scripts/prewarm_profile.py --profile demo
```

Pass an existing profile ID to `--profile`; optional `--valid-at` and `--known-at` select a historical snapshot. The command uses local downloaded weights and changes only derived vectors. Restart the app after replacing model files. Derived vector rows currently accumulate; automatic pruning and approximate nearest-neighbor search remain future work.
