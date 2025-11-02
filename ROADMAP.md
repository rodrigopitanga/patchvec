# Roadmap

Immediate chores worth tackling now. Claim a task by opening an issue titled `claim: <task>` and link your branch or PR when ready.

## 0.5.x Series — Adoption & Stability

### v0.5.7 — Search, Filters, Traceability
- Expand partial filter support (`*` prefix/fuzzy matching).
- Return a `match_reason` field alongside every hit.
- Persist configurable logging per tenant and collection.
- Provide REST/CLI endpoints to delete a document by id.
- Expose latency histograms (p50/p95/p99) via `/metrics` for search and ingest requests.

### v0.5.8 — Persistence, Infrastructure
- Ship an internal metadata/content store (SQLite or TinyDB) with migrations.
- Serve `/metrics` and `/collections` using the internal store as the source of truth.
- Emit structured logs with `request_id`, tenant, and latency, and allow rolling retention per tenant/collection.
- Support renaming collections through the API and CLI.
- Provide per-tenant and per-operation API rate limits

### v0.5.9 — Ranking, Model Quality
- Add hybrid reranking (vector similarity + BM25/token matching).
- Honor `meta.priority` boosts during scoring.
- Improve multilingual relevance and evaluation fixtures.

## 🚀 Towards 1.0

### 0.6 — Per-Collection Embeddings, Data Types
- Configure embeddings per collection via `config.yml`.
- Maintain per-collection hot caches with isolation guarantees.
- List tenants and collections via the API (CLI parity included).
- Lay ground to support new data types (audio, video, image)

### 0.7 — API Utilities & Observability
- Default tenant/collection selectors in Swagger UI.
- Export indexes, enforce collection-level logging toggles, add rate limiting, and finalize per-collection embedding configuration flows.

### 0.8 — Reliability & Governance
- Deliver the internal DB for persistence, document versioning, rebuild tooling, persistent metrics, surfacing metrics in the UI, JWT auth, per-tenant quotas, and transactional rollback with safe retries.

### 0.9 — Scale & Multi-Tenant Search
- Async ingest, parallel purge, horizontal scalability, tenant groups, and shared/group search with sub-index routing.

### 1.0 — API Freeze
- Lock routes, publish the final OpenAPI spec, and ship an SDK client ready for long-term support.
