# Roadmap

Immediate chores worth tackling now. Claim a task by opening an issue titled `claim: <task>` and link your branch or PR when ready.

---

## Business-Aligned Priority Evaluation

> PatchVec is the knowledge base for all Planno products. BNCC.click is the
> first consumer — a teacher-facing GA tool that maps lessons to BNCC skill
> codes via semantic search. The core product metric is **time saved by the
> teacher to reach the correct BNCC codes**. Every PatchVec TODO is evaluated
> below against that metric and the consolidated Planno/Flowlexi strategy.

### P0 — Blocks BNCC.click GA launch

| # | Task | Why it blocks | Source |
|---|------|---------------|--------|
| 1 | **Multilingual embedding model** — switch the default from `paraphrase-MiniLM-L3-v2` (English-centric) to a multilingual model and validate Portuguese retrieval quality | BNCC.click operates entirely in Portuguese. Teachers describe lessons in natural language; the current English-optimized model degrades recall on PT-BR queries. Fidelity ("nao inventa codigo") is the implicit value prop — wrong codes destroy trust. | `txtai_store.py:80-84`, product guideline §5 |
| 2 | **`match_reason` field on every search hit** — return a short explanation of why a BNCC skill matched | Product requirement: "explicar por que aquela habilidade se aplica". Without this, the teacher gets codes but no justification, which undermines confidence and forces manual cross-checking (defeating the time-saving metric). | ROADMAP v0.5.7, product guideline §3 |
| 3 | **Latency histograms (p50/p95/p99)** on `/metrics` for search and ingest | The single success metric is time saved. Without latency instrumentation there is no way to measure, regress-test, or optimize the core value proposition. | ROADMAP v0.5.7, business guideline §7 |
| 4 | **Negation filter performance** — push `!`-prefixed filters into SQL pre-filter instead of post-filter | BNCC.click fires 3 parallel searches per request, two of which use `!Disciplina` negation. Today these go through Python post-filtering (`_split_filters` sends `!` to `pos_f`), which forces a large overfetch and multiplies tail latency. | `txtai_store.py:350-354`, bncc.click code |
| 5 | **Structured request logging with trace_id** — accept and propagate an external `trace_id` / `request_id` through search responses and logs | BNCC.click already generates `trace_id` per request and logs it to Sheets. PatchVec silently drops it. Without correlation, production debugging across the bncc.click -> PatchVec boundary is blind. | ROADMAP v0.5.8, bncc.click code |

### P1 — Critical for first paid pilots (Planno.click B2B)

| # | Task | Why it matters | Source |
|---|------|----------------|--------|
| 6 | **Delete document by ID** (REST + CLI) | BNCC data will be updated (MEC revisions, corrections). Without single-doc deletion, the only option is full collection rebuild — unacceptable operationally. | ROADMAP v0.5.7 |
| 7 | **Hybrid reranking (vector + BM25)** | Teachers search with exact BNCC code fragments ("EF05MA01") mixed with natural language. Pure vector similarity misses exact token matches. Hybrid ranking is the difference between "found it first try" and "had to scroll". | ROADMAP v0.5.9, product guideline §5 |
| 8 | **Per-tenant rate limiting** | BNCC.click is GA and public. Without rate limiting, a single abusive client can saturate the shared PatchVec instance and degrade service for all teachers. | ROADMAP v0.5.8 |
| 9 | **Internal metadata store (SQLite)** with migrations | Current storage is JSON files (`catalog.json`, `meta.json`) written atomically per collection. Under concurrent teacher load this becomes a bottleneck and corruption risk. SQLite gives ACID guarantees the file approach lacks. | ROADMAP v0.5.8 |
| 10 | **Per-collection embedding configuration** | BNCC collection needs a PT-BR-optimized model; future Planno.click collections (lesson plans, assessments) may need different models. Today the model is global. | ROADMAP v0.6 |

### P2 — Enables Planno.school (enterprise light) and moat

| # | Task | Why it matters | Source |
|---|------|----------------|--------|
| 11 | **`meta.priority` scoring boosts** | Planno.school will cross-reference student performance with curriculum coverage. Priority boosts let the system surface high-impact skills first. | ROADMAP v0.5.9 |
| 12 | **List tenants and collections API** | Operational visibility for multi-school deployments. Coordination teams need to know what's indexed. | ROADMAP v0.6 |
| 13 | **Collection-level structured log export** | The moat is "what the system learns without asking" — which skills are searched, which are missing, which combinations appear. This data must be extractable per-collection for analysis. | ROADMAP v0.5.8, business guideline §9 |
| 14 | **Document versioning and rebuild tooling** | When BNCC data is corrected, schools need audit trails. Versioning supports the "dados auditaveis, rastreaveis, reutilizaveis" promise. | ROADMAP v0.8 |

### P3 — Scale and long-term

| # | Task | Source |
|---|------|--------|
| 15 | Async ingest and parallel purge | ROADMAP v0.9 |
| 16 | Horizontal scalability, tenant groups, sub-index routing | ROADMAP v0.9 |
| 17 | JWT auth and per-tenant quotas | ROADMAP v0.8 |
| 18 | API freeze, OpenAPI spec, SDK client | ROADMAP v1.0 |

---

## Source Code Observations

### What is solid

- **Multi-tenant isolation** (`t_{tenant}/c_{collection}` layout) is clean and
  well-tested. BNCC.click already consumes it correctly.
- **Filter system** is expressive (wildcards, comparisons, datetime, negation,
  OR/AND). The bncc.click early code exercises most filter features.
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
   numeric and datetime comparisons. While the inputs are constrained, this is a
   code smell that should be replaced with `operator` module comparisons. It also
   makes the filter path harder to reason about for security audits.

2. **Global singleton at import time** — `main.py:362` calls `build_app()` at
   module level, which instantiates the store and config eagerly. This makes
   testing harder (requires monkeypatching) and prevents lazy initialization.

3. **`assert` in production code** — `txtai_store.py:265` uses `assert` to verify
   chunk text round-trips. Assertions are stripped when Python runs with `-O`.
   This should be a proper check.

4. **Lock dict is not thread-safe** — `txtai_store.py:14-16` (`_LOCKS` dict) is
   accessed without synchronization. Two threads could race to create the same
   lock. Use `threading.Lock()` to guard the dict itself or use
   `collections.defaultdict` with a global lock.

5. **Embedder factory unused** — `pave/embedders/factory.py` exists but is never
   called. The TxtaiStore creates its own Embeddings instance internally
   (`_config()`). This means the pluggable embedder architecture is dead code for
   the default store. Per-collection embedding config (P1-10) will require
   resolving this.

6. **QdrantStore is a dead stub** — Every method raises `NotImplementedError`.
   It ships as a runtime dependency (`qdrant-client` in `setup.py`) but cannot
   be used. This adds ~50MB of install weight for no functionality.

7. **Preprocess module reads config at import** — `preprocess.py:10-11` reads
   `TXT_CHUNK_SIZE` and `TXT_CHUNK_OVERLAP` at module load. Changing config at
   runtime has no effect on chunking parameters.

---

## Market Practices (extracted from real-time decisioning benchmarks)

> PatchVec serves BNCC.click the same way a geo-bidding engine serves ad
> campaigns: both are real-time decisioning systems that must return the right
> answer fast under concurrent load. The patterns below are table-stakes in
> that domain and map directly to Planno's needs.

### 1. Return `latency_ms` in every search response

The XPTO geo-bidding spec mandates `latency_ms` in every response body.
PatchVec currently returns `{matches: [...]}` with no timing information.

**Why it matters for Planno:** The single product metric is "time saved by
the teacher". BNCC.click already logs `trace_id` to Google Sheets. If
PatchVec also returns `latency_ms`, BNCC.click can log it alongside every
request, giving Planno concrete data to prove value to schools ("200ms vs
the 3 minutes you used to spend").

**Gap:** `service.py:do_search()` does not measure wall time. `main.py`
search routes do not inject timing. Neither `SearchBody` response nor any
response schema includes `latency_ms`.

**Effort:** Low. Wrap `do_search` in `time.perf_counter()`, add field to
response dict.

### 2. Define an explicit latency SLO and enforce it in CI

The geo-bidding challenge requires p99 <50ms at 1k req/s. PatchVec has no
SLO, no benchmark suite, no regression gate.

**Why it matters for Planno:** Without a latency contract between PatchVec
and BNCC.click, there is no way to detect regressions before they hit
teachers. Without benchmarks, there is no number to put in sales material.

**Gap:** No benchmark script exists. No CI step validates latency.
`metrics.py` tracks counters but not histograms.

**Action:** Ship a `benchmarks/` directory with a repeatable load test
(e.g., `locust` or plain `httpx` + `asyncio`) that indexes a sample BNCC
CSV, fires concurrent searches, and asserts p99 < threshold. Integrate into
CI as a gating check.

### 3. Hot-reload data and configuration without restart

The geo-bidding spec requires hot-reloading campaign targeting without
downtime. PatchVec's equivalent: updating BNCC data (MEC revisions) or
swapping embedding models without restarting the server.

**Current state:** Document purge + re-index works live (via `purge_doc` +
`ingest_document`). But:
- Embedding model is loaded once at startup (`TxtaiStore._config()` reads
  config at init time, `load_or_init` caches per-collection).
- `preprocess.py` reads `TXT_CHUNK_SIZE` / `TXT_CHUNK_OVERLAP` at import.
- Config changes require process restart.

**Action for v0.5.7:** Document the live-data-update path (purge + ingest)
as an explicit operational procedure. For v0.6 (per-collection embeddings),
design model hot-swap via a `/admin/reload` endpoint.

### 4. Pre-computation beats post-filtering

The geo-bidding "bonus" is spatial indexing (R-tree, grid cells) — pre-
computing indexes so you don't brute-force every request. PatchVec's
equivalent: pushing filters into txtai's SQL query instead of fetching
overfetch × 5 and filtering in Python.

**Current state:** `_split_filters()` (`txtai_store.py:336`) sends `!`-prefixed
values, wildcards, and comparison operators to `pos_f` (Python post-filter).
BNCC.click uses `!Disciplina` negation in 2 of 3 parallel queries, meaning
those queries overfetch and filter in Python.

**Why it matters:** Each BNCC.click request = 3 parallel PatchVec searches.
If 2 of 3 use post-filtering, tail latency multiplies. At 100 concurrent
teachers, this becomes the bottleneck.

**Action:** For negation (`!value`), generate `[field] <> 'value'` in SQL
instead of routing to post-filter. This is txtai-compatible SQL and avoids
the overfetch penalty. Keep wildcards and comparison ops in post-filter
where SQL support is uncertain.

### 5. Graceful degradation under overload

The geo-bidding challenge rewards systems that degrade gracefully (e.g.,
shed low-priority work, return partial results) rather than failing
entirely under load.

**Current state:** PatchVec has no backpressure mechanism. Under high load:
- uvicorn's threadpool fills up silently.
- JSON file I/O (`_load_meta`, `_save_meta`) becomes a bottleneck.
- No circuit breaker, no request shedding, no timeout on search.

**Why it matters for Planno:** BNCC.click is GA and public. A viral moment
(teacher shares on social media) could spike load. Without degradation
strategy, all teachers get 500s instead of some getting slower responses.

**Action for v0.5.8:** Add a configurable search timeout (default 5s). If
exceeded, return partial results with a `"truncated": true` flag. Add a
`max_concurrent_searches` config with 503 Fast-Fail when exceeded.

### 6. Benchmark suite as a first-class artifact

The geo-bidding challenge requires benchmarks in the README as a
deliverable — not optional documentation, but proof of performance claims.

**Why it matters for Planno:** When selling to schools ("reduces
coordination overhead"), you need measurable evidence. When optimizing
PatchVec, you need a regression baseline. When choosing between embedding
models, you need comparable latency/recall numbers.

**Gap:** No `benchmarks/` directory. No load test. No recall evaluation
against a ground-truth BNCC mapping.

**Action:** Create `benchmarks/search_latency.py` (load test) and
`benchmarks/recall_bncc.py` (quality evaluation against hand-labeled PT-BR
queries). Document baseline numbers in README.

### 7. Request/response traceability as contract

The geo-bidding spec includes `request_id` in both request and response.
This is the minimum contract for any system that participates in a
distributed call chain.

**Current state:** BNCC.click generates `trace_id` per request and logs it
to Sheets. PatchVec ignores it — `SearchBody` has no `request_id` field,
`do_search()` doesn't accept one, responses don't echo it.

**Action:** Add optional `request_id` to `SearchBody`. Echo it in response.
Include it in structured log entries. This closes the observability gap
between BNCC.click and PatchVec.

### 8. Concurrency safety as explicit contract (not assumed)

The geo-bidding challenge lists "handles concurrent requests correctly" as a
must-have, not a nice-to-have.

**Current state:** PatchVec has `_LOCKS` dict (`txtai_store.py:14`) which is
itself not thread-safe. Two concurrent `load_or_init` calls for the same
collection can race on `_emb` dict. The `collection_lock()` pattern is
correct for index writes, but the lock registry has a gap.

**Action:** Guard `_LOCKS` with a module-level `threading.Lock()`. Audit
all paths from HTTP handler to store for thread-safety.

### Summary: What the market expects from a real-time decisioning API

| Practice | XPTO (geo-bidding) | PatchVec (BNCC search) | Status |
|----------|-------------------|----------------------|--------|
| Latency in response body | `latency_ms` mandatory | Not returned | **Missing** |
| Latency SLO + benchmarks | p99 <50ms, benchmarks in README | No SLO, no benchmarks | **Missing** |
| Hot-reload without downtime | Campaign hot-reload | Data update works; model swap requires restart | **Partial** |
| Pre-computation / indexing | Spatial indexing bonus | Negation goes to post-filter | **Partial** |
| Graceful degradation | Bonus: shed under overload | No backpressure, no timeout | **Missing** |
| Request ID propagation | `request_id` in req + resp | Not propagated | **Missing** |
| Concurrency safety | Must-have | Lock dict race condition | **Partial** |
| Budget / quota governance | Campaign budget decrement | No rate limiting or quotas | **Missing** |

Five of eight practices are completely missing. Three are partial. None are
fully implemented. All are standard expectations for production decisioning
APIs, and all map directly to Planno's business requirements.

---

## Revised Roadmap (business-aligned)

### v0.5.7 — BNCC.click GA Readiness
- Switch default embedding model to multilingual (e.g., `paraphrase-multilingual-MiniLM-L12-v2`).
- Return a `match_reason` field alongside every search hit.
- Return `latency_ms` in every search response (market practice §1).
- Push `!`-prefixed negation filters into SQL pre-filter (`<>`) for performance (market practice §4).
- Accept and propagate `request_id` / `trace_id` through search requests, responses, and logs (market practice §7).
- Expose latency histograms (p50/p95/p99) via `/metrics` for search and ingest.
- Provide REST/CLI endpoints to delete a document by id.
- Replace `eval()` in filter matching with `operator` module.
- Replace `assert` in `index_records` with a proper runtime check.
- Fix `_LOCKS` dict race condition with a global guard lock (market practice §8).
- Ship initial `benchmarks/` directory with search latency load test (market practice §6).

### v0.5.8 — Infrastructure for Pilots
- Ship internal metadata/content store (SQLite) with migrations.
- Serve `/metrics` and `/collections` from the internal store.
- Emit structured logs with `request_id`, tenant, and latency; rolling retention per tenant/collection.
- Per-tenant and per-operation API rate limits (market practice §8 — budget/quota governance).
- Configurable search timeout + `max_concurrent_searches` with 503 fast-fail (market practice §5).
- Support renaming collections through the API and CLI.

### v0.5.9 — Ranking Quality
- Add hybrid reranking (vector similarity + BM25/token matching).
- Honor `meta.priority` boosts during scoring.
- Multilingual relevance evaluation fixtures (PT-BR test corpus).

### 0.6 — Per-Collection Embeddings & Schema Freeze
- Configure embedding model per collection via `config.yml`.
- Per-collection hot caches with isolation.
- List tenants and collections via API (CLI parity).
- Resolve embedder factory integration with TxtaiStore.
- Remove or gate `qdrant-client` dependency behind extras.
- Freeze search response schema (`matches`, `latency_ms`, `match_reason`, `request_id`).
- Typed response models (internal `SearchResult` dataclass).

### 0.7 — SDK & Orchestrator Integration
- Python SDK client package (`patchvec`).
- LangChain `VectorStore` + `Retriever` adapter (covers LangGraph + CrewAI).
- Default tenant/collection selectors in Swagger UI.
- Collection-level structured log export for analytics.

### 0.8 — MCP, LlamaIndex & Governance
- MCP server (expose search/ingest/list as MCP tools).
- LlamaIndex `VectorStore` adapter.
- Document versioning, rebuild tooling.
- Persistent metrics in the UI.
- JWT auth, per-tenant quotas, transactional rollback.

### 0.9 — Scale
- Async ingest, parallel purge.
- Horizontal scalability, tenant groups, sub-index routing.

### 1.0 — API Freeze
- Lock routes, publish final OpenAPI spec, ship SDK client.

---

## Pluggability: PatchVec as a General-Purpose Vector Search Microservice

> Secondary priority — after BNCC.click GA. But architectural decisions made
> now (v0.5.7–0.6) determine whether this path is cheap or a rewrite.

### The landscape (as of early 2026)

There is **no standard vector store API**. Qdrant, Pinecone, Weaviate,
ChromaDB, Milvus — each has a proprietary REST API. The de facto unifying
layers are:

1. **LangChain `VectorStore`** — the dominant abstraction. Implementing it
   covers LangChain, LangGraph, AND CrewAI (which delegates to LangChain's
   VectorStore internally). Two abstract methods: `add_texts()`,
   `from_texts()`. Plus `similarity_search()`, `similarity_search_with_score()`,
   `delete()` for full functionality.

2. **LlamaIndex `VectorStore`** — second framework. Different interface but
   similar surface: `add()`, `delete()`, `query()`. Supports dense search
   and metadata filtering.

3. **MCP (Model Context Protocol)** — NOT dead. Adopted by OpenAI (March
   2025), Google DeepMind, and hundreds of tool providers. 2026 is the
   enterprise adoption year. Qdrant, Pinecone, and MindsDB already ship MCP
   servers for vector search. MCP lets any compatible AI agent (Claude,
   ChatGPT, custom) search the vector store directly — no SDK needed on the
   agent side.

4. **OpenAI Vector Store API** — proprietary to OpenAI's platform
   (Assistants/Retrieval). NOT a standard others implement. Implementing
   compatibility would be cargo-culting with no adoption benefit.

### What PatchVec has today

| Surface | Status | Notes |
|---------|--------|-------|
| REST API (FastAPI) | **Solid** | OpenAPI spec auto-generated. Well-structured routes. |
| OpenAPI schema | **Solid** | Swagger UI with filtered views (search/ingest). |
| Multi-tenancy | **Solid** | `tenant/collection` namespacing — a real differentiator. |
| File preprocessing | **Unique** | CSV/PDF/TXT built-in. Competitors require external preprocessing. |
| Python SDK (client) | **Missing** | No `patchvec` package for HTTP consumption. |
| LangChain adapter | **Missing** | No `VectorStore` subclass. |
| LlamaIndex adapter | **Missing** | No `VectorStore` implementation. |
| MCP server | **Missing** | No tool exposure for AI agents. |
| gRPC | **Missing** | REST-only. |

### What PatchVec does NOT need

- **OpenAI-compatible API** — There is no "OpenAI vector store standard"
  that third parties implement. OpenAI's Vector Store API is platform-locked.
  Skip.

- **gRPC (short term)** — REST is sufficient for the current latency targets.
  gRPC matters at >10k req/s with sub-5ms budgets. Not the current reality.

- **GraphQL** — No vector store uses it. No framework expects it. Skip.

### What PatchVec needs (in priority order)

#### 1. Python SDK — `patchvec` client package (~150 lines)

A thin HTTP wrapper that maps PatchVec's REST API to Python method calls.
This is the foundation everything else wraps.

```python
from patchvec import PatchVecClient

client = PatchVecClient("http://localhost:8086", api_key="...")
client.create_collection("tenant", "bncc_ef")
client.ingest("tenant", "bncc_ef", file_path="bncc_ef.csv")
results = client.search("tenant", "bncc_ef", "frações equivalentes", k=5)
```

**Why:** Every vector DB ships a client SDK. Without one, PatchVec
integration requires raw `httpx`/`requests` calls, which nobody does in
2026. This is table-stakes.

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
from patchvec.integrations.langchain import PatchVecVectorStore

store = PatchVecVectorStore(
    client=client, tenant="planno", collection="bncc_ef"
)
retriever = store.as_retriever(search_kwargs={"k": 5})
```

**Why:** LangChain is the dominant orchestrator. A single adapter covers
three major frameworks.

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

**Why:** MCP is the standard protocol for AI agent ↔ tool communication.
Qdrant, Pinecone, MindsDB already ship MCP servers. Without one, PatchVec
is invisible to the fastest-growing integration channel. For Planno
specifically: a Planno MCP server backed by PatchVec would let any
MCP-compatible AI assistant search BNCC data directly — opening a
distribution channel beyond BNCC.click's web UI.

**Effort:** ~300 lines. MCP Python SDK is well-documented.

**When:** v0.8 (after API freeze candidates are stable).

#### 4. LlamaIndex adapter (~200 lines)

Similar to LangChain but implements LlamaIndex's `VectorStore` protocol:
- `add(nodes)` → ingest
- `delete(ref_doc_id)` → delete
- `query(query_bundle)` → search with metadata filters

**Why:** Second-largest orchestrator framework. Smaller ROI than LangChain
but completes the coverage.

**When:** v0.8 or v0.9.

### PatchVec's positioning in the vector DB landscape

PatchVec is not Qdrant or Pinecone. It does not compete on billion-vector
scale or sub-millisecond latency. Its niche is:

**"The SQLite of vector search"** — embed it, no cluster, no cloud, good
enough for most workloads under 10M vectors.

| | PatchVec | ChromaDB | Qdrant | Pinecone |
|---|---------|----------|--------|----------|
| Deployment | Single-process, file-based | Single-process, file-based | Docker/K8s or managed | Managed only |
| Multi-tenancy | Built-in (`tenant/collection`) | No | Namespaces | Namespaces |
| File preprocessing | CSV/PDF/TXT built-in | No | No | No |
| Embedding choice | Pluggable (3 backends) | BYO embeddings | BYO embeddings | BYO embeddings |
| Filtering | Expressive (wildcards, negation, datetime, comparisons) | Basic metadata | Rich (Qdrant-native) | Basic metadata |
| License | GPL-3.0 | Apache-2.0 | Apache-2.0 | Proprietary |

The **built-in preprocessing** and **multi-tenancy** are real
differentiators. ChromaDB, the closest lightweight competitor, has neither.

### Architectural decisions that affect pluggability NOW

These are decisions in v0.5.7–0.6 that determine whether the integration
layer (v0.7+) is cheap or expensive:

1. **Stabilize the search response schema** — If `do_search()` returns
   `{matches: [{id, score, text, meta}]}` today and changes later, every
   adapter breaks. Freeze the response shape in v0.5.7. Add new fields
   (`latency_ms`, `match_reason`, `request_id`) now, so the schema is
   stable by v0.6.

2. **Document delete by ID** (P1-6) — LangChain's `delete()` method
   requires this. Without it, the LangChain adapter ships incomplete.

3. **Per-collection embedding config** (0.6) — LangChain's `from_texts()`
   passes an `embedding` parameter. PatchVec must be able to accept
   external embeddings OR let the caller specify which model to use.
   Currently the model is global and internal to TxtaiStore.

4. **List collections** (P2-12) — Both LangChain and MCP need enumeration.
   Without it, users must know collection names ahead of time.

5. **`BaseStore.search()` return type** — Currently returns
   `List[Dict[str, Any]]`. For SDK/adapter consumption, a typed dataclass
   (e.g., `SearchResult(id, score, text, meta)`) would be cleaner. This is
   a v0.6 candidate.

### Integration roadmap (post BNCC.click GA)

| Version | Deliverable | Depends on |
|---------|------------|------------|
| v0.7 | Python SDK (`patchvec` client package) | Stable REST API (v0.6) |
| v0.7 | LangChain `VectorStore` adapter | SDK + doc delete (P1-6) |
| v0.8 | MCP server | SDK + list collections (P2-12) |
| v0.8 | LlamaIndex adapter | SDK |
| v0.9 | Typed response models (`SearchResult` dataclass) | API freeze candidate |
| 1.0 | Published integrations on PyPI (`patchvec-langchain`, `patchvec-mcp`) | API freeze |

### What this means for the revised version milestones

**v0.6** gains:
- Freeze search response schema (add `latency_ms`, `match_reason`, `request_id`).
- List collections API (enables MCP and LangChain enumeration).
- Typed return models as internal preparation.

**v0.7** gains:
- Python SDK client package.
- LangChain VectorStore adapter.

**v0.8** gains:
- MCP server.
- LlamaIndex adapter.
