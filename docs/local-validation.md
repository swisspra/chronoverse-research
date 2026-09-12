# Local validation record

This file distinguishes completed checks from deployment work that still requires a running target. Final browser and transport results are appended after execution.

## Source review

All supplied source documents, draft fragments and duplicates were inventoried privately outside this repository. One external fact-table implementation was reviewed read-only for its identity/revision pattern. No unrelated service was contacted or modified.

## Kernel and protocol tests

The integrated Python suite passed 38 tests. It covers half-open intervals, late knowledge, source/evidence visibility, corrections/retractions, conflicts, scope-before-ranking, graph isolation, durable reload, idempotency and concurrent writes, immutable SQL rows, successor validation, cycle rejection, API validation/static serving, MCP tool calls in modern and legacy modes, and real local semantic embeddings.

One dependency warning remains: Starlette's TestClient imports the deprecated `anyio.abc.BlockingPortal` alias. It does not fail the suite and application code does not import that alias.

The model was downloaded and real local inference produced 384-dimensional vectors. A paraphrase query ranked a relevant sentence above an unrelated weather sentence. This is an inference smoke check, not a multilingual or domain retrieval benchmark.

## Fixture evaluation

With local semantic vectors enabled, all six synthetic temporal/scope diagnostic cases passed. The unscoped lexical baseline passed zero of six because these cases were selected to require explicit temporal/epistemic filtering. This result does not establish superiority over GraphRAG or performance on real documents.

## Packaging

`az bicep build --file deploy/azure-vm.bicep --outfile deploy/azure-vm.json` succeeded and produced five ARM resources. `docker compose config --quiet` succeeded. Docker daemon connectivity failed at the configured local socket, so no image build or container run was claimed. No Azure resource was provisioned.

## Live application and MCP

The complete `./scripts/dev.sh` command installed dependencies, built the production frontend and started both services. Real HTTP MCP calls passed with negotiated versions `2026-07-28` and `2025-11-25`; both listed all five tools and returned three main-world fact assertions. A real stdio subprocess also returned the shared catalog successfully.

Browser interaction confirmed the same valid date returns a reported injury count of 12 before the correction and 2 after it. Both date controls remain populated after date-only presets; successful searches no longer show a false pending-changes badge. Semantic vector labels match the actual backend engine. Graph selection changes the evidence inspector and the timeline renders the selected snapshot.

The browser ingestion form created synthetic assertion `a-12d2ac84309541b48cfc8c5d0f1c1d42` in world `qa-validation`. After both services stopped and restarted, the assertion and its source persisted. It is excluded from the default main-world view. The local API returned 200 to a normal health request and 400 to an untrusted Host. Automated tests also exercise explicit MCP Host and Origin rejection even with container-style binding.

## Final browser acceptance

The Evaluation page initially failed because a structured query object was rendered directly as a React child. A regression test using the actual API response reproduced the failure, and the result component now renders query text plus expandable coordinates. The live browser subsequently displayed all six cases, with 6/6 Chronoverse checks passing.

Keyboard editing of the knowledge date from September 3 to September 2 changed the reported count from 2 back to 12. Including retired assertions exposed the original report with status Corrected, its original source, correction reason, effective date, recorded date and replacement ID. Graph-edge selection, semantic-vector view and timeline view were exercised. Browser resource inspection showed no third-party requests in the final build.

The 390×844 mobile viewport had document width 390 with no horizontal overflow. The 1440×1050 desktop layout was visually inspected. Captures: `docs/workbench-mobile.png` and `docs/workbench-desktop.png`.

Initial MVP acceptance totals: 38 Python tests and 4 frontend tests. The production frontend build passed.

## Profiles, document import and integrated diagrams — September 12 extension

The current suite passes **60 Python tests and 9 frontend tests**. The production frontend build passes. Added coverage includes profile isolation even when assertion IDs match, scoped events/details and MCP calls, restart durability, atomic rollback, duplicate imports and concurrent replay, nullable imported IDs, expired preview renewal, profile-bound commit tokens, malformed/deep JSON, UTF-8 validation, bounded text PDF extraction, encrypted/scanned PDFs, partial empty-page warnings and HTTP upload size limits. The existing upstream Starlette/AnyIO deprecation warning remains.

Real browser acceptance created `Document Sandbox` (`p-b253476ddebd4984982c59bc9c8436cc`) from the profile selector. Its initial ledger was empty. A Markdown document containing English and Thai text, a TXT document and a text PDF were previewed together. Preview left the ledger empty; commit added three report-plane source passages. A malformed PDF and an image-only/blank PDF showed separate actionable errors. Returning directly to Workbench displayed the committed records with their recommended scope. Re-uploading the Markdown file reported `0 added · 1 already present`; profile count remained three.

Searching `NebulaMandarin`, `OrbitSaffron` and `CopperNebula` ranked the corresponding Markdown, TXT and PDF sources first through live semantic HTTP MCP calls. These are synthetic smoke markers, not a quality benchmark. Inspecting their IDs in `demo` returned errors. Switching profiles cleared the query/inspector and restored demo data; reloading remembered the selected profile. After both services stopped and restarted, the API catalog and all three source passages persisted, and MCP profile search passed in both protocol modes (`2026-07-28`, `2025-11-25`). All six read-only tools were listed.

The original demo database retained exactly the same 17 assertion and 3 event payloads: sorted ID/payload SHA-256 hashes matched the pre-extension snapshot. Raw passage graph labels include document identity so unrelated documents never join through the ordinal label `Passage 1`.

Browser inspection exercised Graph-RAG and Graph-RAG + Time, Fit/zoom controls, section jumps and shared inspector selection of the corrected injury count. The timeline distinguishes active green windows from muted dashed historical windows for corrected/retracted/superseded records. Its wording separates stored/effective validity windows from applicability at the selected snapshot. SVG downloads were triggered through the real UI and include embedded styles, query/profile/scope, full ISO timestamp tooltips, counts and legends. Export removes display zoom and uses fixed dimensions. Captures and exports:

- `document-upload.png`: upload screen with dataset profile.
- `profiles-mobile.png`: 390×844 layout; document width remained 390, profile creation control worked, and mobile navigation retained accessible names.
- `profiles-desktop.png`: combined workbench overview.
- `graph-rag-timeline.png`: evidence flow and timeline with the corrected original claim selected.
- `demo-graph-rag-timeline.svg` and `uploaded-graph-rag-timeline.svg`: actual standalone browser exports.

Browser resource inspection found no third-party requests. Services remain running on loopback ports 8000 and 8001. PDF support requires extractable text; OCR and automatic fact extraction remain unimplemented. The supplied English-oriented embedding model has not been benchmarked for Thai retrieval. Local profiles separate datasets, not authenticated users. Azure/container runtime validation remains at the earlier documented boundary.
