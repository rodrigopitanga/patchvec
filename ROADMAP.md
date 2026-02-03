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

## Revised Roadmap (business-aligned)

### v0.5.7 — BNCC.click GA Readiness
- Switch default embedding model to multilingual (e.g., `paraphrase-multilingual-MiniLM-L12-v2`).
- Return a `match_reason` field alongside every search hit.
- Push `!`-prefixed negation filters into SQL pre-filter for performance.
- Accept and propagate `trace_id` / `request_id` through search requests and logs.
- Expose latency histograms (p50/p95/p99) via `/metrics` for search and ingest.
- Provide REST/CLI endpoints to delete a document by id.
- Replace `eval()` in filter matching with `operator` module.
- Replace `assert` in `index_records` with a proper runtime check.
- Fix `_LOCKS` dict race condition with a global guard lock.

### v0.5.8 — Infrastructure for Pilots
- Ship internal metadata/content store (SQLite) with migrations.
- Serve `/metrics` and `/collections` from the internal store.
- Emit structured logs with `request_id`, tenant, and latency; rolling retention per tenant/collection.
- Per-tenant and per-operation API rate limits.
- Support renaming collections through the API and CLI.

### v0.5.9 — Ranking Quality
- Add hybrid reranking (vector similarity + BM25/token matching).
- Honor `meta.priority` boosts during scoring.
- Multilingual relevance evaluation fixtures (PT-BR test corpus).

### 0.6 — Per-Collection Embeddings
- Configure embedding model per collection via `config.yml`.
- Per-collection hot caches with isolation.
- List tenants and collections via API (CLI parity).
- Resolve embedder factory integration with TxtaiStore.
- Remove or gate `qdrant-client` dependency behind extras.

### 0.7 — Observability & Tooling
- Default tenant/collection selectors in Swagger UI.
- Collection-level structured log export for analytics.
- Index export tooling.

### 0.8 — Reliability & Governance
- Document versioning, rebuild tooling.
- Persistent metrics in the UI.
- JWT auth, per-tenant quotas, transactional rollback.

### 0.9 — Scale
- Async ingest, parallel purge.
- Horizontal scalability, tenant groups, sub-index routing.

### 1.0 — API Freeze
- Lock routes, publish final OpenAPI spec, ship SDK client.
