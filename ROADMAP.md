<!-- (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net> -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Roadmap

tl;dr: This roadmap tracks production readiness and integration milestones. To claim a
task, open an issue titled `claim: <task ID>` and link your branch or PR.

> PatchVec is a general-purpose vector search microservice. The roadmap that follows
> below is driven by production readiness for its first downstream consumer — an
> application that maps natural-language queries to structured codes via semantic search
> in a non-English language. The core product metric is **time saved to reach the
> correct results**. Every TODO is evaluated against that metric and general production
> readiness.

## Design Principles

These are non-negotiable constraints that apply across all versions.

- **Zero boilerplate by default.** A working setup requires no org, workspace, profile,
  or grouping ceremony. Create a collection and go. Groupings, limits, and profiles are
  opt-in — never required for a basic setup.
- **Collection independence.** Collections are not owned by tenants. The tenant is a
  runtime namespace, not a structural owner. Collections must be fully portable: export
  from one instance/tenant, import into another without data loss or format surprise.
- **Transparency by default.** Developers must be able to see what was indexed, what
  chunks were produced, what metadata is stored. Opacity is a DX failure.
- **Layered independence.** Auth, tenant profiles, collections, and server configuration
  are orthogonal concerns. No layer forces coupling to another. A tenant can exist
  without a profile; a collection can exist without a custom embedding config.
- **Optional tenant groupings ("syndicates").** When tenant grouping is needed (e.g.
  for org-level quotas or shared collections), it is expressed as a lightweight syndicate
  — an opt-in overlay, not a mandatory hierarchy. No boilerplate orgs/workspaces.
- **Server and library are the same thing.** PatchVec must run equally well as an HTTP
  microservice and as an in-process Python library (embedded, single-tenant, no uvicorn).
  The service layer is the API; HTTP is just one transport.
- **Media types are progressive, not baked in.** Text is the baseline. Every additional
  media type (images, audio, video, and beyond) is added through a stable ingest plugin
  interface without touching the core. The plugin contract must be stable before any
  specific media type ships.
- **Collections are version-safe.** Every collection records the PatchVec and schema
  version it was written with. Incompatible reads must fail loudly with actionable
  guidance, not silently corrupt. Migration tooling ships alongside breaking changes.
- **PatchVec enforces limits; it does not govern business logic.** Resource limits,
  quotas, and tier profiles are read from a manifest and applied at runtime. Billing,
  onboarding, and payment are outside PatchVec's scope — it just reads a file.

---

## Priority Evaluation (external driver)

### P0 — Blocks first consumer GA launch

Size legend: 🧩 bite-sized, 🧱 foundational

| ID | Task | Size | Why it blocks | Source |
|---|---|---|---|---|
| P0-01 | ~~**Multilingual embedding model**~~ |  | Non-EN recall | `txtai_store.py` |
| P0-02 | ~~**`match_reason` on every hit**~~ |  | Trust + explanation gap | v0.5.7 |
| P0-03 | ~~**Latency histograms**~~ |  | No latency visibility | v0.5.7 |
| P0-04 | ~~**Negation pre-filter**~~ |  | Tail latency | `txtai_store.py` |
| P0-05 | ~~**`trace_id` propagation**~~ |  | No request correlation | v0.5.8 |

### P1 — Critical for first B2B pilots

| ID | Task | Size | Why it matters | Source |
|---|---|---|---|---|
| P1-06 | ~~**Delete doc by ID**~~ | 🧩 | No partial data fixes | v0.5.7 |
| P1-07 | **Hybrid reranking** | 🧱 | Exact token boost | v0.5.9 |
| P1-08 | **Per-tenant rate limiting** |  | Abuse protection | v0.5.8 |
| P1-09 | **Metadata store (SQLite)** | 🧱 | ACID + concurrency | v0.5.8 |
| P1-10 | **Per-collection embeddings** | 🧱 | Model per collection | v0.6 |
| P1-11 | **Global `request_id` echo** | 🧩 | Traceability | v0.6 |
| P1-12 | ~~**Ingest timeout guidance**~~ | 🧩 | Avoid client timeouts | v0.5.8 |
| P1-13 | **Ingest size limits** | 🧩 | Fail fast on huge uploads | v0.5.8 |
| P1-14 | **Response envelope standardization** | 🧱 | SDK-friendly API | v0.6 |
| P1-15 | **Embedded/library mode** | 🧱 | In-app use, adoption | v0.7 |
| P1-16 | **Batch ingest endpoint** | 🧩 | Throughput, DX | v0.7 |
| P1-17 | **Get document by ID** | 🧩 | Visibility, library mode | v0.7 |

### P2 — Enables enterprise use cases and competitive moat

| ID | Task | Size | Why it matters | Source |
|---|---|---|---|---|
| P2-11 | **`meta.priority` boosts** |  | Surface priority items | v0.5.9 |
| P2-12 | ~~**List tenants/collections API**~~ | 🧩 | Ops visibility | v0.6 |
| P2-13 | **Collection log export** | 🧱 | Search analytics | v0.5.8 |
| P2-14 | **Document versioning** | 🧱 | Audit trails | v0.8 |
| P2-19 | **Tenant admin infra** | 🧱 | Admin ops | v0.6 |
| P2-20 | **Collection limit / tenant** | 🧩 | Cap growth | v0.6 |
| P2-21 | **Storage limit / tenant** | 🧩 | Cap storage | v0.6 |
| P2-22 | **Usage stats to mothership** |  | Capacity planning | v0.7 |
| P2-23 | **Developer visibility tools** | 🧱 | DX, debuggability | v0.7 |
| P2-24 | **Delete by ID list / by query** | 🧩 | Bulk ops, DX | v0.8 |
| P2-25 | **Collection version tagging** | 🧩 | Portability, migration | v0.6 |
| P2-26 | **Tenant profiles + templates** | 🧱 | Quota governance, tiers | v0.8 |
| P2-27 | **Image ingest + embeddings** | 🧱 | Multimodal adoption | v0.8 |

### P3 — Scale and long-term

| ID | Task | Size | Source |
|---|---|---|---|
| P3-15 | Async ingest + parallel purge |  | v0.9 |
| P3-16 | Horizontal scalability + routing | 🧱 | v0.9 |
| P3-17 | JWT auth + per-tenant quotas | 🧱 | v0.8 |
| P3-18 | API freeze + SDK client | 🧱 | v1.0 |
| P3-23 | Docs website | 🧩 | v0.7 |
| P3-24 | Revamp UI | 🧱 | v0.7 |
| P3-25 | Multilingual UI/errors/docs | 🧱 | v0.7 |
| P3-26 | Embedder/store contract | 🧱 | v0.6 |
| P3-27 | Chunking strategies | 🧱 | v0.9 |
| P3-28 | Extensible ingest plugin architecture | 🧱 | v0.8 |
| P3-29 | Audio/video ingest + embeddings | 🧱 | v0.9 |
| P3-30 | Retain original uploaded files (opt-in) | 🧱 | v0.9 |
| P3-31 | Async ingest jobs + job status API | 🧱 | v0.9 |
| P3-32 | Per-tenant parallel ingest limits | 🧱 | v0.9 |
| P3-33 | Tenant job notifications (webhook/email) | 🧱 | v1.0+ |
| P3-34 | Relicensing (AGPLv3 candidate) | 🧱 | v0.5.9 |
| P3-35 | Rebranding (PaveDB candidate) | 🧱 | v0.6 |
| P3-36 | Multimodal collections (cross-modal search) | 🧱 | v1.0+ |
| P3-37 | Collection migration tooling (version compat) | 🧱 | v0.8 |
| P3-38 | Tenant syndicates (opt-in grouping, no mandatory hierarchy) | 🧱 | v1.0+ |

---

## Release Schedule (internal driver)

### v0.1 — Prototype
- First search + ingest pipeline; single-tenant, FAISS-backed, sbert embeddings.
- CLI-driven TXT ingestion and REST search endpoint; minimal auth stub.

### v0.2 — Isolation
- Multi-tenant routing (`/{tenant}/{collection}`) with per-tenant API key auth.
- Collection creation, deletion, and document management endpoints.

### v0.3 — Extension
- QdrantStore skeleton, OpenAI embedder proof of concept, unified `CFG` config.
- Full CLI mode added.

### v0.4 — Modularity
- Codebase split into `stores/`, `embedders/`, `auth.py`, `service.py`, `cli.py`,
  `preprocess.py`, `metrics.py`.

### v0.5 — Pluggability
- `BaseStore` ABC, `StoreFactory` + `EmbedderFactory`; runtime backend selection.
- `/health` endpoint; `DummyStore` for isolated testing.

### v0.5.1 — Hardening
- Auth refactored into dependency-injected `auth_ctx()`; unified GET/POST search.
- Comprehensive pytest suite; factories migrated to `match` syntax.

### v0.5.2 — Ingestion
- CSV and PDF ingest alongside TXT; `TxtaiEmbedder`, `OpenAIEmbedder`, `SbertEmbedder`.
- Fixed JSON body search route; docker-compose stub added.

### v0.5.3 — Foundation
- Makefile release flow, GitLab/GitHub CI/CD, `.env.example`, `tenants.yml`.
- README split into user + contributor docs; REST curl examples; PyPI install path.

### v0.5.4 — Launch
- Initial public release; CSV ingestion knobs, deterministic doc-ID re-ingest.
- Request metrics standardized; Docker GPU/CPU + PyPI publish pipeline bootstrapped.

### v0.5.5 — Refinement
- FAISS index initialization on collection creation; correct text retrieval from store.
- Auth edge cases fixed; entry point hardened for production binding.

### v0.5.6 — Deployment
- Docker GPU/CPU split pipeline; Swagger/OpenAPI UI with branding and auth helpers.
- Ingestion timestamps; improved FAISS concurrency and chunk text persistence fallback.

### v0.5.7 — Readiness
- ~~Switch default embedding model to multilingual (e.g., `paraphrase-multilingual-
MiniLM-L12-v2`).~~
- ~~Return a `match_reason` field alongside every search hit.~~
- ~~Return `latency_ms` in every search response (market practice §1).~~
- ~~Push `!`-prefixed negation filters into SQL pre-filter (`<>`) for performance
(market practice §4).~~
- ~~Accept and propagate `request_id` / `trace_id` through search requests, responses,
and logs (market practice §7).~~
- ~~Expose latency histograms (p50/p95/p99) via `/metrics` for search and ingest.~~
- ~~Provide REST/CLI endpoints to delete a document by id.~~
- ~~Document the live-data-update path (purge + ingest).~~
- ~~Replace `eval()` in filter matching with `operator` module.~~
- ~~Replace `assert` in `index_records` with a proper runtime check.~~
- ~~Fix `_LOCKS` dict race condition with a global guard lock (market practice §8).~~
- ~~Ship initial `benchmarks/` directory with search latency load test (market practice
§6).~~
- ~~Push legacy typing synthax to Python 3.10~~
- ~~Update copyright notices, polish logging infrastructure~~

### v0.5.8 — Resilience
Order: must first, then should.
- Error code standardization (consistent codes/messages).
- Add ingest size limits with clear errors.
- ~~Document ingest timeout guidance (client/proxy/uvicorn).~~
- Make `build_app()` lazy; avoid eager app creation at import time.
- Configurable search timeout + `max_concurrent_searches` with 503 fast-fail (market
practice §5).
- Per-tenant and per-operation API rate limits (market practice §8 — quota governance).
- Ship internal metadata/content store (SQLite) with migrations.
- Serve `/metrics` and `/collections` from the internal store.
- Emit structured logs with `request_id`, tenant, and latency; rolling retention per
tenant/collection.
- ~~Support renaming collections through the API and CLI.~~

### v0.5.9 — Relevance
Order: must first, then should.
- Honor `meta.priority` boosts during scoring.
- Add hybrid reranking (vector similarity + BM25/token matching).
- Multilingual relevance evaluation fixtures (non-English test corpus).
- Run benchmark suite in CI; publish results as artifacts; define p99
  latency SLO gate (closes Market Practice §2 gap).
- Relicensing review (AGPLv3 candidate).
- Response envelope standardization (v0.6 prep).

### 0.6 — Stability
Order: must first, then should.
- Define embedder/store separation contract (txtai models vs FAISS store).
- Resolve embedder factory integration with TxtaiStore.
- Tenant admin infrastructure (limits, visibility, controls).
- Per-tenant collection count limit.
- Per-tenant storage limit.
- Configure embedding model per collection via `config.yml`.
- Per-collection hot caches with isolation.
- Freeze search response schema (`matches`, `latency_ms`, `match_reason`, `request_id`).
- Response envelope standardization (consistent success/error shape).
- Collection version tagging (PatchVec version + schema version baked into collection
  metadata at creation/write time — foundation for portability and migration).
- Formalize collection independence from tenant: tenant is a namespace, not an owner;
  collections must be fully exportable and importable across instances and tenants.
- Publish `pip freeze` snapshot as a release artifact alongside Docker images.
- Rebranding review (PaveDB candidate).
- ~~List tenants and collections via API (CLI parity).~~
- ~~Typed response models (internal `SearchResult` dataclass).~~
- ~~Remove or gate `qdrant-client` dependency behind extras.~~

### 0.7a — Adoption
- Python client package (`pave`): HTTP mode for remote instances; library mode for
  in-process use (no HTTP). Same package, two transports.
- Embedded/library mode: run PatchVec in-process without HTTP server (expose
  service + store layer as a Python API; single-tenant default).
- Batch ingest endpoint (list of documents in one call).
- Get document by ID endpoint (retrieve text + metadata for a known docid).

### 0.7b — Reach
- `pavecli --host`: route CLI commands through the HTTP client instead of the service
  layer directly; depends on Python client. CLI becomes a thin wrapper.
- JavaScript/TypeScript client: typed, bootstrapped from OpenAPI spec, published to
  npm. Covers web frontends and Node.js backends.
- LangChain `VectorStore` + `Retriever` adapter (covers LangGraph + CrewAI).
- Developer visibility tools: chunk inspector, indexed document browser, metadata
  explorer — debuggability as a first-class feature.
- Default tenant/collection selectors in Swagger UI.
- Collection-level structured log export for analytics.
- Alive test in CI pipeline (post-deploy health check against a real environment).
- Docs website (public docs, API reference).
- Revamp UI.
- Multilingual support for UI, error messages, and docs.
- Usage stats to mothership (opt-in/anon).

### 0.8 — Governance
- MCP server (expose search/ingest/list as MCP tools).
- LlamaIndex `VectorStore` adapter.
- Go client: generated from OpenAPI spec, published as a Go module; covers
  cloud-native and infrastructure consumers.
- Document versioning, rebuild tooling.
- Persistent metrics in the UI.
- JWT auth, per-tenant quotas, transactional rollback.
- Extensible ingest plugin architecture (foundation for additional media types;
  plugin interface must be stable before any specific media type ships).
- Image ingest + embeddings (separate image collections, CLIP-style models;
  multimodal collections deferred to post-1.0).
- Delete by ID list and delete by metadata query (single-collection scope first).
- Tenant profiles: manifest-driven resource limits (memory, storage, concurrency,
  models available), profile templates (e.g. free/paid tiers); PatchVec enforces
  limits, does not handle billing or onboarding.
- Collection migration tooling: detect version mismatches, provide upgrade path
  across PatchVec/txtai/FAISS version changes.
- Commit to independence principle: auth, tenant profiles, collections, and
  server config are orthogonal — no coupling between layers.

### 0.9 — Scale
- Async ingest, parallel purge.
- Horizontal scalability, tenant groups, sub-index routing.
- Chunking strategies (semantic, hybrid) foundations.
- Retain original uploaded files, opt-in (originals + versioning hooks).
- Async ingest jobs with status tracking API.
- Per-tenant parallel ingest limits.
- Audio/video ingest + embeddings (transcription pipeline for audio; key-frame +
  audio track for video; separate collections, multimodal deferred).
- Matrix CI builds (Python 3.10/3.11/3.12 × core ML versions) as pre-1.0
  compatibility gate.

### 1.0 — Contract
- Lock routes, publish final OpenAPI spec, ship SDK client.
- Additional media types: graphic/geom (feature detection).
- Additional media types: AV (transcriptions, pattern detection).
- Additional media types: georeferenced content.
- Tenant job notifications (webhook/email).
- Audit logs for admin actions.

### 1.0+ — Post-freeze backlog (no IDs yet)
- Rust client (WASM target; browser-side or embedded use cases).
- Multimodal collections: images, audio, and text in a shared vector space
  (cross-modal search; requires model architecture commitment).
- Vector dimension/schema guardrails.
- Soft-delete + TTL policies.
- Snapshot/backup automation.
- Index rebuild / compaction tooling.
- Filter indexes / prefilter cache.
- Drift/quality monitoring.
- Resource limits (RAM/index caps).
- Cold-start mitigation (warming hooks).
- Approx-search tuning config.

---

## Source Code Observations

### What is solid

- **Multi-tenant isolation** (`t_{tenant}/c_{collection}` layout) is clean and
well-tested. Production consumers already use it correctly.
- **Filter system** is expressive (wildcards, comparisons, datetime, negation,
OR/AND). Real consumer code exercises most filter features.
- **SQL injection prevention** (`_sanit_sql`, `_sanit_field`, `_sanit_meta_dict`)
is thorough and has dedicated tests.
- **Pluggable architecture** (BaseStore/BaseEmbedder ABCs, factory pattern) makes
it straightforward to swap backends without touching consumers.
- **Chunk text sidecar storage** guarantees text is always retrievable even when
the vector index loses content — a practical reliability win.
- **Auth policy enforcement** (`enforce_policy`) correctly prevents auth=none in
production. The loopback-only dev mode is a good guardrail.
- **Data archive/restore** with lock acquisition is operationally useful for
backup and migration.

### What needs attention (code-level)

1. **`eval()` in filter matching** — `txtai_store.py:309,315` uses `eval()` for
numeric and datetime comparisons. While the inputs are constrained, this is a code smell
that should be replaced with `operator` module comparisons. It also makes the filter
path harder to reason about for security audits. (done v0.5.7)

2. **Global singleton at import time** — `main.py:362` calls `build_app()` at
module level, which instantiates the store and config eagerly. This makes testing harder
(requires monkeypatching) and prevents lazy initialization. (schedule v0.5.8)

3. **`assert` in production code** — `txtai_store.py:265` uses `assert` to verify
chunk text round-trips. Assertions are stripped when Python runs with `-O`. This should
be a proper check. (done v0.5.7)

4. **Lock dict is not thread-safe** — `txtai_store.py:14-16` (`_LOCKS` dict) is
accessed without synchronization. Two threads could race to create the same lock. Use
`threading.Lock()` to guard the dict itself or use `collections.defaultdict` with a
global lock. (done v0.5.7)

5. **Embedder factory unused** — `pave/embedders/factory.py` exists but is never
called. The TxtaiStore creates its own Embeddings instance internally (`_config()`).
This means the pluggable embedder architecture is dead code for the default store. Per-
collection embedding config (P1-10) will require resolving this. (schedule v0.6)

6. **QdrantStore is a dead stub** — Every method raises `NotImplementedError`.
It ships as a runtime dependency (`qdrant-client` in `setup.py`) but cannot be used.
This adds ~50MB of install weight for no functionality. (schedule v0.6)

7. **Preprocess module reads config at import** — `preprocess.py:10-11` reads
`TXT_CHUNK_SIZE` and `TXT_CHUNK_OVERLAP` at module load. Changing config at runtime has
no effect on chunking parameters. (schedule v0.6)

---

## Market Practices (extracted from real-time decisioning benchmarks)

> PatchVec serves downstream consumers the same way a geo-bidding engine
> serves ad campaigns: both are real-time decisioning systems that must
> return the right answer fast under concurrent load. The patterns below
> are table-stakes in that domain.

### 1. Return `latency_ms` in every search response

Real-time decisioning APIs mandate `latency_ms` in every response body. PatchVec now
returns `latency_ms` (done v0.5.7).

**Why it matters:** The core metric for consumers is time saved. If PatchVec returns
`latency_ms`, consumers can log it alongside every request, giving operators concrete
data to prove and monitor value.

**Gap:** None. (done v0.5.7)

**Effort:** Low. Wrap `do_search` in `time.perf_counter()`, add field to response dict.

### 2. Define an explicit latency SLO and enforce it in CI

Production decisioning APIs require p99 latency SLOs. PatchVec has no SLO, no benchmark
suite, no regression gate.

**Why it matters:** Without a latency contract between PatchVec and its consumers, there
is no way to detect regressions before they hit end users. Without benchmarks, there is
no baseline to optimize against.

**Gap:** No CI SLO gate. No repeatable latency benchmarks tied to CI.

**Action:** Ship a `benchmarks/` directory with a repeatable load test (e.g., `locust`
or plain `httpx` + `asyncio`) that indexes a sample dataset, fires concurrent searches,
and asserts p99 < threshold. Integrate into CI as a gating check.

### 3. Hot-reload data and configuration without restart

Production APIs require hot-reloading configuration without downtime. PatchVec's
equivalent: updating indexed data or swapping embedding models without restarting the
server.

**Current state:** Document purge + re-index works live (via `purge_doc` +
`ingest_document`). But:
- Embedding model is loaded once at startup (`TxtaiStore._config()` reads
config at init time, `load_or_init` caches per-collection).
- `preprocess.py` reads `TXT_CHUNK_SIZE` / `TXT_CHUNK_OVERLAP` at import.
- Config changes require process restart.

**Action for v0.5.7:** ~~Document the live-data-update path (purge + ingest)~~ as an
explicit operational procedure. For v0.6 (per-collection embeddings), design model hot-
swap via a `/admin/reload` endpoint.

### 4. Pre-computation beats post-filtering

The equivalent of spatial indexing for geo queries: pushing filters into txtai's SQL
query instead of fetching overfetch x 5 and filtering in Python.

**Current state:** `_split_filters()` (`txtai_store.py:336`) sends `!`-prefixed values,
wildcards, and comparison operators to `pos_f` (Python post-filter). Consumers using
`!`-negation in parallel queries overfetch and filter in Python.

**Why it matters:** If consumers fire multiple parallel searches and most use post-
filtering, tail latency multiplies. At scale, this becomes the bottleneck.

**Action:** For negation (`!value`), generate `[field] <> 'value'` in SQL instead of
routing to post-filter. This is txtai-compatible SQL and avoids the overfetch penalty.
Keep wildcards and comparison ops in post-filter where SQL support is uncertain. Status:
done v0.5.7.

### 5. Graceful degradation under overload

Production APIs must degrade gracefully (e.g., shed low-priority work, return partial
results) rather than failing entirely under load.

**Current state:** PatchVec has no backpressure mechanism. Under high load:
- uvicorn's threadpool fills up silently.
- JSON file I/O (`_load_meta`, `_save_meta`) becomes a bottleneck.
- No circuit breaker, no request shedding, no timeout on search.

**Why it matters:** Public-facing consumers may experience traffic spikes. Without
degradation strategy, all users get 500s instead of some getting slower responses.

**Action for v0.5.8:** Add a configurable search timeout (default 5s). If exceeded,
return partial results with a `"truncated": true` flag. Add a `max_concurrent_searches`
config with 503 Fast-Fail when exceeded.

### 6. Benchmark suite as a first-class artifact

Performance benchmarks are not optional documentation — they are proof of performance
claims and regression gates.

**Why it matters:** When optimizing PatchVec, you need a regression baseline. When
choosing between embedding models, you need comparable latency/recall numbers. When
consumers evaluate PatchVec against alternatives, benchmarks are the first thing they
look for.

**Gap:** ~~No `benchmarks/` directory. No load test.~~ No recall evaluation against a
ground-truth dataset.

**Action:** Create `benchmarks/search_latency.py` (load test) and
`benchmarks/recall_eval.py` (quality evaluation against hand-labeled queries). Document
baseline numbers in README.

### 7. Request/response traceability as contract

Distributed systems require `request_id` in both request and response. This is the
minimum contract for any service that participates in a call chain.

**Current state:** `request_id` is accepted and echoed (done v0.5.7).

**Action:** Add optional `request_id` to `SearchBody`. Echo it in response. Include it
in structured log entries. This closes the observability gap between consumers and
PatchVec. (done v0.5.7)

### 8. Concurrency safety as explicit contract (not assumed)

Production APIs must handle concurrent requests correctly as a must-have, not a nice-to-
have.

**Current state:** PatchVec has `_LOCKS` dict (`txtai_store.py:14`) which is itself not
thread-safe. Two concurrent `load_or_init` calls for the same collection can race on
`_emb` dict. The `collection_lock()` pattern is correct for index writes, but the lock
registry has a gap.

**Action:** Guard `_LOCKS` with a module-level `threading.Lock()`. Audit all paths from
HTTP handler to store for thread-safety. (done v0.5.7)

### Summary: What the market expects from a real-time decisioning API

| Practice | Geo-bidding benchmark | PatchVec | Status |
|----------|----------------------|----------|--------|
| Latency in response body | `latency_ms` | Returned by search | **DONE** |
| Latency SLO + benchmarks | p99 <50ms | No CI gate | **Missing** |
| Hot-reload without downtime | Hot reload | Model swap needs restart | **Partial** |
| Pre-computation / indexing | Precompute | Negation pre-filter | **DONE** |
| Graceful degradation | Shed load | No backpressure | **Missing** |
| Request ID propagation | `request_id` | Echoed in responses | **DONE** |
| Concurrency safety | Thread-safe | Lock dict guarded | **DONE** |
| Budget / quota governance | Quotas | No rate limits | **Missing** |

Five of eight practices are completely missing. Three are partial. None are fully
implemented. All are standard expectations for production decisioning APIs.

---

## Pluggability: PatchVec as a General-Purpose Vector Search Microservice

> Secondary priority — after the first consumer reaches GA. But
> architectural decisions made now (v0.5.7–0.6) determine whether this
> path is cheap or a rewrite.

### The landscape (as of early 2026)

There is **no standard vector store API**. Qdrant, Pinecone, Weaviate, ChromaDB, Milvus
— each has a proprietary REST API. The de facto unifying layers are:

1. **LangChain `VectorStore`** — the dominant abstraction. Implementing it
covers LangChain, LangGraph, AND CrewAI (which delegates to LangChain's VectorStore
internally). Two abstract methods: `add_texts()`, `from_texts()`. Plus
`similarity_search()`, `similarity_search_with_score()`, `delete()` for full
functionality.

2. **LlamaIndex `VectorStore`** — second framework. Different interface but
similar surface: `add()`, `delete()`, `query()`. Supports dense search and metadata
filtering.

3. **MCP (Model Context Protocol)** — NOT dead. Adopted by OpenAI (March
2025), Google DeepMind, and hundreds of tool providers. 2026 is the enterprise adoption
year. Qdrant, Pinecone, and MindsDB already ship MCP servers for vector search. MCP lets
any compatible AI agent (Claude, ChatGPT, custom) search the vector store directly — no
SDK needed on the agent side.

4. **OpenAI Vector Store API** — proprietary to OpenAI's platform
(Assistants/Retrieval). NOT a standard others implement. Implementing compatibility
would be cargo-culting with no adoption benefit.

### What PatchVec has today

| Surface | Status | Notes |
|---------|--------|-------|
| REST API (FastAPI) | **Solid** | OpenAPI spec; clean routes. |
| OpenAPI schema | **Solid** | Swagger UI with filtered views (search/ingest). |
| Multi-tenancy | **Solid** | `tenant/collection` namespacing — a real differentiator. |
| File preprocessing | **Unique** | CSV/PDF/TXT built-in. |
| Python SDK (client) | **Missing** | No `pave` package for HTTP consumption. |
| LangChain adapter | **Missing** | No `VectorStore` subclass. |
| LlamaIndex adapter | **Missing** | No `VectorStore` implementation. |
| MCP server | **Missing** | No tool exposure for AI agents. |
| gRPC | **Missing** | REST-only. |

### What PatchVec does NOT need

- **OpenAI-compatible API** — There is no "OpenAI vector store standard"
that third parties implement. OpenAI's Vector Store API is platform-locked. Skip.

- **gRPC (short term)** — REST is sufficient for the current latency targets.
gRPC matters at >10k req/s with sub-5ms budgets. Not the current reality.

- **GraphQL** — No vector store uses it. No framework expects it. Skip.

### What PatchVec needs (in priority order)

#### 1. Python SDK — `pave` client package (~150 lines)

A thin HTTP wrapper that maps PatchVec's REST API to Python method calls. This is the
foundation everything else wraps.

```python
from pave import PaveClient

client = PaveClient("http://localhost:8086", api_key="...")
client.create_collection("tenant", "my_collection")
client.ingest("tenant", "my_collection", file_path="data.csv")
results = client.search("tenant", "my_collection", "example query", k=5)
```

**Why:** Every vector DB ships a client SDK. Without one, PatchVec integration requires
raw `httpx`/`requests` calls, which nobody does in 2026. This is table-stakes.

**Effort:** Low. ~150 lines wrapping the existing REST endpoints.

**When:** v0.7 (after API stabilizes in 0.6).

#### 2. LangChain `VectorStore` adapter (~200 lines)

Implement `langchain_core.vectorstores.VectorStore`:
- `add_texts(texts, metadatas)` → calls `POST /collections/{t}/{c}/documents`
- `similarity_search(query, k, filter)` → calls `POST /collections/{t}/{c}/search`
- `similarity_search_with_score(query, k)` → same, returns scores
- `delete(ids)` → calls document delete endpoint (needs P1-6 first)
- `from_texts(texts, embedding)` → creates collection + ingests

This single adapter covers:
- **LangChain** chains and agents
- **LangGraph** stateful agent graphs
- **CrewAI** agents and tools (delegates to LangChain VectorStore)

```python
from pave.integrations.langchain import PaveVectorStore

store = PaveVectorStore(
    client=client, tenant="my_tenant", collection="my_collection"
)
retriever = store.as_retriever(search_kwargs={"k": 5})
```

**Why:** LangChain is the dominant orchestrator. A single adapter covers three major
frameworks.

**Effort:** ~200 lines. Depends on Python SDK.

**When:** v0.7 (immediately after SDK).

#### 3. MCP server (~300 lines)

Expose PatchVec operations as MCP tools:
- `search_collection(tenant, collection, query, k, filters)` → search
- `ingest_document(tenant, collection, file_path)` → upload
- `list_collections(tenant)` → list (needs P2-12 first)

```json
{
  "name": "search_collection",
  "description": "Search a PatchVec collection using semantic similarity",
  "parameters": {
    "tenant": "string",
    "collection": "string",
    "query": "string",
    "k": "integer"
  }
}
```

**Why:** MCP is the standard protocol for AI agent ↔ tool communication. Qdrant,
Pinecone, MindsDB already ship MCP servers. Without one, PatchVec is invisible to the
fastest-growing integration channel. An MCP server backed by PatchVec lets any MCP-
compatible AI assistant search indexed data directly.

**Effort:** ~300 lines. MCP Python SDK is well-documented.

**When:** v0.8 (after API freeze candidates are stable).

#### 4. LlamaIndex adapter (~200 lines)

Similar to LangChain but implements LlamaIndex's `VectorStore` protocol:
- `add(nodes)` → ingest
- `delete(ref_doc_id)` → delete
- `query(query_bundle)` → search with metadata filters

**Why:** Second-largest orchestrator framework. Smaller ROI than LangChain but completes
the coverage.

**When:** v0.8 or v0.9.

### PatchVec's positioning in the vector DB landscape

PatchVec is not Qdrant or Pinecone. It does not compete on billion-vector scale or sub-
millisecond latency. Its niche is:

**"The SQLite of vector search"** — embed it, no cluster, no cloud, good enough for most
workloads under 10M vectors.

| | PatchVec | ChromaDB | Qdrant | Pinecone |
|---|---------|----------|--------|----------|
| Deployment | Single-process | Single-process | Docker/K8s | Managed |
| Multi-tenancy | Built-in | No | Namespaces | Namespaces |
| File preprocessing | CSV/PDF/TXT | No | No | No |
| Embedding choice | Pluggable | BYO | BYO | BYO |
| Filtering | Expressive | Basic | Rich | Basic |
| License | GPL-3.0 | Apache-2.0 | Apache-2.0 | Proprietary |

The **built-in preprocessing** and **multi-tenancy** are real differentiators. ChromaDB,
the closest lightweight competitor, has neither.

### Architectural decisions that affect pluggability NOW

These are decisions in v0.5.7–0.6 that determine whether the integration layer (v0.7+)
is cheap or expensive:

1. **Stabilize the search response schema** — If `do_search()` returns
`{matches: [{id, score, text, meta}]}` today and changes later, every adapter breaks.
Freeze the response shape in v0.5.7. Add new fields (`latency_ms`, `match_reason`,
`request_id`) now, so the schema is stable by v0.6.

2. **Document delete by ID** (P1-6) — LangChain's `delete()` method
requires this. Without it, the LangChain adapter ships incomplete.

3. **Per-collection embedding config** (0.6) — LangChain's `from_texts()`
passes an `embedding` parameter. PatchVec must be able to accept external embeddings OR
let the caller specify which model to use. Currently the model is global and internal to
TxtaiStore.

4. ~~**List collections** (P2-12)~~ — Both LangChain and MCP need enumeration.
Status: done.

5. ~~**`BaseStore.search()` return type** — Currently returns
`List[Dict[str, Any]]`. For SDK/adapter consumption, a typed dataclass (e.g.,
`SearchResult(id, score, text, meta)`) would be cleaner. This is a v0.6 candidate.~~

### Integration roadmap

| Version | Deliverable | Depends on |
|---------|------------|------------|
| v0.7.0 | Python client (`pave`): HTTP + library mode | Stable REST API (v0.6) |
| v0.7.0 | Embedded mode, batch ingest, get-doc-by-ID | Python client |
| v0.7.5 | `pavecli --host` (remote CLI via HTTP client) | Python client |
| v0.7.5 | JS/TS client (npm) | OpenAPI spec (auto-generated, then typed) |
| v0.7.5 | LangChain `VectorStore` adapter | Python client |
| v0.8 | Go client (Go module, generated) | Stable OpenAPI spec |
| v0.8 | MCP server | Python client |
| v0.8 | LlamaIndex adapter | Python client |
| ~~v0.9~~ | ~~Typed response models~~ | ~~API freeze~~ |
| 1.0 | Published integrations on PyPI/npm (`pave-langchain`, `pave-mcp`) | API freeze |
| 1.0+ | Rust client (WASM target) | API freeze |

### What this means for the revised version milestones

**v0.6** gains:
- Freeze search response schema (add `latency_ms`, `match_reason`, `request_id`).
- ~~List collections API (enables MCP and LangChain enumeration).~~
- Typed return models as internal preparation.

**v0.7** gains:
- Python SDK client package.
- LangChain VectorStore adapter.

**v0.8** gains:
- MCP server.
- LlamaIndex adapter.
