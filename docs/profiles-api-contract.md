# Dataset profiles and file import API

All existing `/api/meta`, `/api/query`, `/api/assertions`, `/api/assertions/{id}`, assertion POST/event POST, and `/api/evaluate` routes accept **`?profile_id=...`**, default `demo`. Existing schemas remain compatible; data responses add `profile_id`. Unknown IDs return 404; malformed IDs return 422. IDs are `demo` or opaque `p-<32 lowercase hexadecimal digits>`. Profile names never become paths. No shared active-profile state exists.

## Profiles

`GET /api/profiles` → `{profiles:[{id,name,created_at,is_demo,counts:{assertions,events}}],default_profile_id:"demo"}`.

`POST /api/profiles` JSON `{name:string}` → profile object (201). Name 1–100 characters, trimmed; duplicate names return 409. Newly created profile is empty. Catalog and independent SQLite ledgers persist beside the existing demo database under `profiles/`.

`GET /api/meta?profile_id=...` adds `profile:{id,name,created_at,is_demo}`, `profile_id`, and `import_formats:["pdf","txt","md","json","jsonl","csv"]`. New profiles default valid_at/known_at to current UTC and examples to `[]`. Demo retains fixed September 2026 coordinates. Explicit dates always win. Query requests omitting dates use the selected profile defaults; detail/meta endpoints behave similarly. `/api/evaluate` remains the isolated synthetic demo diagnostic, regardless of selected profile; response includes selected `profile_id` and `evaluation_profile_id:"demo"` so UI must label it synthetic/demo-only.

## Preview → commit

`POST /api/imports/preview?profile_id=...` multipart form with one file field **`file`**. No additional fields required. File max 10 MiB; max 500 assertions/passages; PDF max 200 pages; extracted text max 2,000,000 characters. File extensions `.pdf`, `.txt`, `.md`, `.markdown`, `.json`, `.jsonl`, `.csv` only. No URL fetching, script execution, OCR or automatic fact extraction.

Returns (200): `{preview_id,profile_id,filename,format,content_hash,assertion_count,document_count,warnings:string[],sample_assertions:[AssertionInput],recommended_scope:{valid_at,known_at,world:string,plane:"all",perspective:"all"}}`. At most five sample assertions. `content_hash` is exact original-file SHA-256. Preview validates the entire upload without changing assertions/events. Prepared previews persist across restart and expire after 24 hours. Preview IDs are bound to the target profile; committing them elsewhere returns 404.

`POST /api/imports/commit?profile_id=...` JSON `{preview_id:string}` → `{profile_id,preview_id,filename,content_hash,inserted_count,existing_count,assertion_ids:string[],recommended_scope:{valid_at,known_at,world:string,plane:"all",perspective:"all"}}`. All rows commit in one SQLite transaction. Any invalid/conflicting row rolls back the whole upload. Replaying the same prepared upload or re-previewing identical bytes is idempotent within each profile; response reports existing_count. Commit never changes another profile. Limit errors return 413; malformed content/rows and encrypted/scanned PDFs return 422 with actionable detail. ID payload conflicts return 409.

Raw PDF/TXT/Markdown files become `plane:"report"`, `world:"main"`, `perspective:"document"` assertions: document subject → `contains passage` → passage label. Evidence retains extracted source text, file hash and PDF page locator in its title; summary explicitly says this is source content, not extracted truth. Raw imports use stable document/passage IDs derived from file bytes and passage index. UTF-8 text is required. Text PDF extraction preserves readable text but does not promise original visual layout; scanned PDFs require OCR outside this MVP. Raw imported validity/knowledge times default to import time, which describes corpus availability rather than the truth dates of embedded statements.

Structured JSON accepts one AssertionInput, an array, or `{assertions:[...]}`. JSONL accepts one assertion per nonblank line. CSV requires `subject,predicate,object,valid_from,evidence_title,evidence_text`; optional columns `id,world,plane,perspective,valid_to,recorded_at,summary,evidence_url,synthetic`. Structured files supply explicit assertions with evidence and dates; omitted IDs and recorded_at receive stable values for an identical upload. See downloadable templates below. `sample_assertions` are previews only; commit uses validated server-side prepared records, not edited client samples.

`GET /api/imports/templates/{format}` downloads a small example for `txt`, `md`, `json`, `jsonl`, or `csv`. These are static templates and contain explicitly synthetic content. No PDF template is generated.

## Shared Python interface for MCP

`from chronoverse.profiles import ProfileManager`

- `ProfileManager(demo_path)` opens the catalog beside the existing demo ledger; `.close()` closes owned connections.
- `.list_profiles()` → list of profile objects; `.create_profile(name)` → profile; `.get_profile(profile_id)` → profile metadata.
- `.get_store(profile_id="demo")` → existing `Store`; validates/resolves ID. New profiles are never seeded.
- `.default_scope(profile_id="demo")` → `{valid_at,known_at,world,plane,perspective}`.
- `.query(profile_id, QueryRequest(...))` → existing query response plus `profile_id`; fills only dates not explicitly supplied in `QueryRequest.model_fields_set`.
- `.meta(profile_id="demo", known_at=None)` → profile-aware metadata described above.
- Read detail/events via `.get_store(profile_id)` using `.default_scope(profile_id)` for omitted dates; attach profile_id in MCP wrapper responses.

`from chronoverse.imports import ImportService`

`ImportService(manager).preview(profile_id, filename, content:bytes)` and `.commit(profile_id, preview_id)` return HTTP-equivalent payloads. Import tools are not automatically exposed to MCP; current MCP remains read-only.

Recommended import scope uses the first assertion's valid_from and world, with known_at at least the current time and all assertion recorded_at values. Mixed worlds/validity intervals produce a warning. Raw passage labels contain a document hash so passage 1 in two documents never becomes the same graph node.

PDF extraction runs in a separate process with a 20-second wall timeout, a 15-second CPU limit and a 1 GiB address-space limit where POSIX resource limits are available. Empty pages in mixed text/scanned PDFs produce warnings; entirely extractionless PDFs are rejected with OCR guidance. The HTTP body limit is 10 MiB plus 64 KiB multipart overhead, followed by the exact 10 MiB file limit.

Re-previewing identical bytes reuses the original prepared interpretation, source filename and timestamps, and renews the preview validity window. This also applies after preview expiry and across process restarts; original document bytes are represented by their hash and extracted passage text, not retained as a downloadable binary. New filenames do not duplicate an existing identical-byte upload within a profile. Structured `id:null` is treated like an omitted ID and receives a stable generated ID.
