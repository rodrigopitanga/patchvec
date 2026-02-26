<!-- (C) 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net> -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# PLAN-SQLITE — Internal SQLite Store Roadmap

PatchVec replaces ad-hoc JSON/filesystem metadata with a layered SQLite store.
Each phase adds a new layer; earlier phases are prerequisites for later ones.

Note: txtai already uses SQLite internally for its content/metadata store.
This plan adds our own SQLite layer for catalog, metadata, and operational state
that txtai does not manage.

---

## Phase 1 — Per-Collection Metadata Store (catalog + meta.json replacement)

**Target: v0.5.8**

### Problem

`TxtaiStore` maintains two JSON files per collection:

- `catalog.json` — `{docid: [rid, ...]}` — which chunk IDs belong to a document
- `meta.json` — `{rid: {k: v, ...}}` — metadata dict per chunk

Both are protected by a `threading.Lock` per collection. The critical path issue
is in `search()`:

```python
with collection_lock(tenant, collection):   # acquired
    raw = em.search(sql)                    # FAISS vector search — can be 100ms+
    ...
    meta = self._load_meta(tenant, collection)  # full meta.json load — INSIDE lock
```

Consequences:
1. Concurrent searches on the same collection are fully serialized
2. `_load_meta` deserializes the entire collection's metadata on every search,
   O(N chunks)
3. No ACID on ingest/purge — two separate `os.replace()` calls, no transaction

### Schema

One `meta.db` per collection at `{data_dir}/t_{tenant}/c_{collection}/meta.db`.

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    docid       TEXT PRIMARY KEY,
    version     INTEGER NOT NULL DEFAULT 1,
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    meta_json   TEXT    -- doc-level metadata: filename, content_type, custom fields
);

CREATE TABLE IF NOT EXISTS chunks (
    docid       TEXT NOT NULL,
    rid         TEXT PRIMARY KEY,
    chunk_path  TEXT,                        -- path to sidecar .txt file on disk
    meta_json   TEXT NOT NULL DEFAULT '{}',  -- per-chunk only: page, position, etc.
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS chunks_docid ON chunks (docid);
```

`chunks` replaces both JSON files:
- catalog role: `SELECT rid FROM chunks WHERE docid = ?`
- metadata role: `SELECT rid, meta_json FROM chunks WHERE rid IN (...)`

`documents` tracks re-ingest history and document-level state:
- `version` increments on each purge+reinsert:
  `COALESCE((SELECT version FROM documents WHERE docid=?), 0) + 1`
- `ingested_at` reflects the most recent ingest timestamp
- Not a full version history (that's Phase 4) — just a monotonic counter for
  visibility and debugging
- `meta_json` — document-level metadata (filename, content_type, and any custom
  fields passed at ingest). Chunks carry only genuinely per-chunk fields (page,
  position, section). **Migration note:** current `chunks.meta_json` holds a mix
  of doc-level and chunk-level fields as a workaround (no document row existed
  before); those doc-level fields migrate here when `TxtaiStore` is updated.
- Original file retention is a P3-30 concern (opt-in); field naming TBD there.
  Any derivative document produced mid-pipeline either becomes chunks or is
  referenced via metadata — no separate file row needed.

**`docid` assignment rules** (consistent across file and non-file sources):
- Explicit caller-provided `docid` → used as-is
- File source, no docid → derived from filename (current behaviour)
- Non-file source (string, stream), no docid → UUID generated at ingest time

**Content hash** — deferred. Same content can represent two distinct entities so
a content hash must never be used as an identity. It is still valuable as a
fingerprint for smart re-ingest skipping (avoid re-chunking and re-embedding
unchanged content when the model has not changed), but that requires keeping
the original document on disk. Tracked under P3-30 (retain original uploaded
files, opt-in).

### Chunk vs document metadata split

`chunks.meta_json` holds only per-chunk fields (page, position, section).
Doc-level fields (filename, content_type, ingest-time custom fields) live in
`documents.meta_json` — not replicated on every chunk row.

Trade-off: hydrating a chunk with doc-level metadata requires a JOIN
(`chunks JOIN documents ON chunks.docid = documents.docid`). In practice this
is rarely needed on the hot path: txtai returns whatever metadata was indexed at
ingest time, so `get_meta_batch` (per-chunk WAL read, no JOIN) covers the common
search case. The JOIN path is reserved for explicit doc-metadata lookups.

### Why JSON blob and not K/V rows

Pre-filters go into txtai's own internal SQL via `em.search()`. Our store is
never queried for pre-filtering. Only post-filter matching (wildcards, comparisons)
and result hydration use our metadata. K/V rows add JOIN complexity with no
query benefit.

### Migration system

Integer-versioned DDL applied on first `open()`. Version state in
`schema_migrations`. Clean start only: no JSON import.

**Legacy JSON detection:** if `catalog.json` or `meta.json` exist in the collection
directory, raise `LegacyMetadataError` with a clear message. Prevents silent data
loss on upgrade.

### New module: `pave/meta_store.py`

```python
class CollectionDB:
    def open(self, path: Path) -> None
        # Opens/creates meta.db. Detects legacy JSON. Applies migrations.
        # Pragmas: WAL, busy_timeout=5000, synchronous=NORMAL.

    def upsert_chunks(
        self,
        docid: str,
        chunks: list[tuple[str, str | None, dict]],  # (rid, chunk_path, per-chunk meta)
        doc_meta: dict | None = None,                # doc-level meta
                                                     # → documents.meta_json
    ) -> None
        # INSERT OR REPLACE chunks via executemany.
        # Upserts documents row: bumps version, refreshes ingested_at, stores doc_meta.
        # All in one transaction. Inside collection_lock.

    def delete_doc(self, docid: str) -> list[str]
        # SELECT rid WHERE docid=? then DELETE chunks WHERE docid=?.
        # Deletes documents row too (purge is a full removal).
        # No RETURNING (requires SQLite ≥3.35). Inside collection_lock.

    def has_doc(self, docid: str) -> bool
    def get_rids_for_doc(self, docid: str) -> list[str]
    def get_doc_version(self, docid: str) -> int | None
        # Returns current version or None if docid not found.

    def get_meta_batch(self, rids: list[str]) -> dict[str, dict]
        # Short-circuits on empty list.
        # Chunks IN list at 999 to respect SQLite variable limit.
        # Called OUTSIDE collection_lock.

    def close(self) -> None
```

Connection: one persistent connection per instance, `check_same_thread=False`,
WAL mode, `busy_timeout=5000ms`.

### Key change in `TxtaiStore.search()`

```python
# BEFORE: meta load inside lock — serializes all concurrent searches
with collection_lock(tenant, collection):
    raw = em.search(sql)
    meta = self._load_meta(...)   # O(N), INSIDE lock

# AFTER: FAISS inside lock, meta read outside
with collection_lock(tenant, collection):
    raw = em.search(sql)          # lock covers FAISS only

meta_batch = col_db.get_meta_batch(candidate_rids)   # WAL read, concurrent
```

### Concurrency model

| Operation | Lock held | Meta I/O |
|-----------|-----------|----------|
| `index_records` | `collection_lock` | SQLite write inside lock |
| `purge_doc` | `collection_lock` | SQLite write inside lock |
| `has_doc` | none | SQLite WAL read |
| `search` — FAISS | `collection_lock` | FAISS only |
| `search` — meta | none | SQLite WAL read, concurrent |

### Files changed

| File | Change |
|------|--------|
| `pave/meta_store.py` | New — `CollectionDB` |
| `pave/stores/txtai_store.py` | Replace JSON I/O with `CollectionDB` |
| `tests/test_meta_store.py` | New — unit tests |

### What this does not change

- `service.py`, `main.py`, `BaseStore` — no signature changes
- `DummyStore` / `SpyStore` — unchanged
- Chunk text sidecars (`chunks/*.txt`) — unchanged
- Filter architecture — pre-filters still go to txtai SQL
- `list_tenants` / `list_collections` — still filesystem walk

### Performance expectations

- **p50**: modest improvement (JSON parse eliminated from search hot path)
- **p95/p99**: significant improvement (concurrent searches no longer serialize
  on meta load)

### Benchmark protocol (required)

- Run `benchmarks/search_latency.py` and `benchmarks/stress.py` before and after
  each phase. Save the raw outputs in `benchmarks/results/` with clear names:
  `phase-1-before-<date>.txt`, `phase-1-after-<date>.txt`, etc.
- Keep the same parameters for the before/after pair.
- Tune parameters until p95/p99 visibly separate from p50 (avoid masked results).
  Increase `--concurrency` and `--queries`/`--duration` as needed.

Example (adjust as needed for your machine):

```bash
python benchmarks/search_latency.py --queries 400 --concurrency 32 \
  | tee benchmarks/results/phase-1-before-2026-02-25.txt
python benchmarks/stress.py --duration 180 --concurrency 24 \
  | tee benchmarks/results/phase-1-before-2026-02-25.stress.txt
```

---

## Phase 2 — Global Store (tenant + collection listing)

**Target: v0.6**

### Problem

`list_tenants` and `list_collections` walk the filesystem and check for file
presence. This works but does not scale and cannot support doc/chunk counts or
per-collection metadata without reading every collection's `meta.db`.

### Schema

One `catalog.db` at `{data_dir}/catalog.db`.

```sql
CREATE TABLE IF NOT EXISTS collections (
    tenant       TEXT NOT NULL,
    name         TEXT NOT NULL,   -- slug: URL-safe, used in paths/URLs/keys
    display_name TEXT,            -- human label; free-form, shown in UI/responses
    meta_json    TEXT,            -- operator metadata: description, tags, owner, etc.
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (tenant, name)
);
```

**`name` (slug) assignment rules:**
- Explicit API-provided slug → used as-is
- Display name provided (typical UI flow) → slug auto-derived: lowercase,
  spaces → underscores, strip non-alphanum/dash/underscore
- Neither provided → UUID

The slug is the stable identity used in filesystem paths, URLs, and all
internal keys. `display_name` is what users see and can rename freely without
affecting paths or existing references. Same principle applies to tenants when
a tenant registry is introduced.

`created_at` is automatic (SQLite DEFAULT) — zero maintenance, answers
"how old is this collection?" for visibility and governance.
Doc and chunk counts are derived on demand from each collection's Phase 1
`meta.db` (`SELECT COUNT(DISTINCT docid), COUNT(*) FROM chunks`) — no
separate documents table needed and no sync burden.

### `GlobalDB` class (new in `pave/meta_store.py`)

```python
class GlobalDB:
    def open(self, path: Path) -> None
    def register_collection(self, tenant: str, name: str) -> None
    def unregister_collection(self, tenant: str, name: str) -> None
    def rename_collection(self, tenant: str, old: str, new: str) -> None
    def list_tenants(self) -> list[str]
    def list_collections(self, tenant: str) -> list[str]
        # Returns collection names; counts derived from per-collection meta.db
    def close(self) -> None
```

One global write lock (`threading.Lock`) for writes; WAL for concurrent reads.

### Integration

- `TxtaiStore.__init__` opens `GlobalDB` from `data_dir`
- `create_collection` / `delete_collection` / `rename_collection` → sync `GlobalDB`
- `service.list_collections` and `service.list_tenants` → delegate to `GlobalDB`
- Filesystem walk kept as fallback during transition only

---

## Phase 3 — Operational State (auth, tenant profiles, rate limits, metrics,
log retention)

**Target: v0.7 / v0.8**

### Auth progression

`tenants.yml` is the source of truth for API keys until Phase 3 ships:

```
tenants.yml (now)  →  SQL key store (Phase 3)  →  + OIDC/JWT opt-in (P3-17, v0.8)
```

API keys (`api_keys` table) are a permanent first-class auth method — simple
deployments never need anything else. OIDC/JWT is additive: if
`auth.oidc.issuer` is configured, PatchVec accepts either a valid API key or a
valid JWT on any request. JWT validation is stateless (signature check against
IdP public key); no new table needed for it. See ROADMAP P3-17.

**YAML seed:** on first boot after Phase 3 migration, read `cfg.get('tenants')`
and for each tenant entry INSERT OR IGNORE into `tenant_profiles`, populating
`max_concurrent` from `tenants.<name>.max_concurrent` and the global default
from `tenants.default_max_concurrent`. The `rate_limit_buckets` table (below)
is the target for moving-window rate limiting seeded from `tenants.max_rpm`.

**Seed logic:** on first boot after Phase 3 migration, for each tenant in
`tenants.yml`:
- If tenant not in `api_keys` → insert with key hashed (SHA256 or bcrypt)
- If already present → skip (SQL wins; YAML is not re-applied)

After seeding, `tenants.yml` is only read for limits/profile fallback until
those migrate to `tenant_profiles`. Per-tenant limits defined in `tenants.yml`
today (`max_req_per_min`, `max_collections`, etc.) seed `tenant_profiles` by
the same logic.

**`api_keys` table:**

```sql
CREATE TABLE IF NOT EXISTS api_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant     TEXT NOT NULL,
    key_hash   TEXT NOT NULL UNIQUE,
    label      TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    revoked    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS api_keys_tenant ON api_keys (tenant);
```

One tenant → many keys. Rotation: issue new key, revoke old row. No restart
needed. The global bootstrap key (`PATCHVEC_GLOBAL_KEY` env var) stays outside
SQL permanently — it is the credential used to access the system before any
tenant is provisioned.

**Key management API** (new endpoints, v0.8):
- `POST /admin/tenants` — provision tenant (slug, display_name, limits)
- `POST /admin/tenants/{tenant}/keys` — generate key, returns plaintext once
- `DELETE /admin/tenants/{tenant}/keys/{id}` — revoke key

### What gets persisted

**Tenant profiles** — resource limits and tier config. Seeds from `tenants.yml`
on first boot; SQL is source of truth thereafter. PatchVec enforces limits;
billing/onboarding are out of scope.

```sql
CREATE TABLE IF NOT EXISTS tenant_profiles (
    tenant          TEXT PRIMARY KEY,
    display_name    TEXT,
    max_collections INTEGER,
    max_storage_mb  INTEGER,
    max_concurrent  INTEGER,   -- per-tenant concurrent request cap (0 = unlimited)
    max_req_per_min INTEGER,
    tier            TEXT,
    meta_json       TEXT   -- operator metadata: description, tags, cost-center, etc.
);
```

**Rate limit state** — per-tenant, per-operation counters with TTL.

```sql
CREATE TABLE IF NOT EXISTS rate_limit_buckets (
    tenant      TEXT NOT NULL,
    operation   TEXT NOT NULL,   -- 'search', 'ingest', 'global'
    window_start TEXT NOT NULL,  -- ISO8601 truncated to window
    count        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant, operation, window_start)
);
```

**Aggregate metrics** — doc/chunk counts by collection for `/metrics` and admin
endpoints. (Prometheus counters for latency/search totals stay in-process.)

```sql
-- Doc/chunk counts derived from per-collection meta.db; no new table needed.
-- Structured search/ingest event log for per-tenant analytics:
CREATE TABLE IF NOT EXISTS operation_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant      TEXT NOT NULL,
    collection  TEXT,
    operation   TEXT NOT NULL,   -- 'search', 'ingest', 'delete'
    request_id  TEXT,
    latency_ms  REAL,
    status      TEXT,            -- 'ok', 'error'
    ts          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS op_log_tenant ON operation_log (tenant, ts);
```

Rolling retention enforced per tenant/collection (configurable window, default 30d).
Powers P2-13 collection log export.

**Per-collection embedding model config** — stores which model a collection was
created with, for P1-10 (per-collection embeddings).

```sql
ALTER TABLE collections ADD COLUMN embed_model TEXT;
ALTER TABLE collections ADD COLUMN embed_config_json TEXT;
```

---

## Phase 4 — Governance (syndicates, audit, versioning, usage, jobs)

**Target: v0.8 / v1.0**

### Collection versioning

Every collection records the PatchVec version and schema version it was written
with. Incompatible reads fail loudly with actionable guidance.

```sql
ALTER TABLE collections ADD COLUMN patchvec_version TEXT;
ALTER TABLE collections ADD COLUMN schema_version    INTEGER;
ALTER TABLE collections ADD COLUMN created_at        TEXT;
```

`created_at` not tracked today; added here when we start recording it.

### Document versioning

```sql
CREATE TABLE IF NOT EXISTS document_versions (
    tenant      TEXT NOT NULL,
    collection  TEXT NOT NULL,
    docid       TEXT NOT NULL,
    version     INTEGER NOT NULL,
    ingested_at TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    PRIMARY KEY (tenant, collection, docid, version)
);
```

Powers P2-14 audit trails and future rollback tooling.

### Audit log

Admin-action audit trail (collection create/delete/rename, tenant changes).

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    actor      TEXT,            -- tenant or 'admin'
    action     TEXT NOT NULL,   -- 'create_collection', 'delete_doc', etc.
    tenant     TEXT,
    collection TEXT,
    detail_json TEXT
);
```

### Usage stats

Opt-in, anonymized telemetry for capacity planning (P2-22).

```sql
CREATE TABLE IF NOT EXISTS usage_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    tenant_count   INTEGER,
    collection_count INTEGER,
    doc_count      INTEGER,
    chunk_count    INTEGER,
    reported       INTEGER NOT NULL DEFAULT 0  -- 0=pending, 1=sent
);
```

### Syndicates (opt-in tenant groupings)

Lightweight overlay for org-level quotas and shared collections. No mandatory
hierarchy; a tenant exists without a syndicate.

```sql
CREATE TABLE IF NOT EXISTS syndicates (
    id    TEXT PRIMARY KEY,   -- syndicate slug
    name  TEXT,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS syndicate_members (
    syndicate_id TEXT NOT NULL REFERENCES syndicates(id),
    tenant       TEXT NOT NULL,
    role         TEXT,        -- 'admin', 'member'
    PRIMARY KEY (syndicate_id, tenant)
);
```

### Async ingest job status (P3-31)

```sql
CREATE TABLE IF NOT EXISTS ingest_jobs (
    job_id      TEXT PRIMARY KEY,
    tenant      TEXT NOT NULL,
    collection  TEXT NOT NULL,
    status      TEXT NOT NULL,   -- 'queued', 'running', 'done', 'failed'
    submitted_at TEXT NOT NULL,
    finished_at  TEXT,
    chunk_count  INTEGER,
    error        TEXT
);
```

### Collection migration records (P3-37)

```sql
CREATE TABLE IF NOT EXISTS collection_migrations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant          TEXT NOT NULL,
    collection      TEXT NOT NULL,
    from_version    INTEGER,
    to_version      INTEGER,
    migrated_at     TEXT NOT NULL,
    status          TEXT NOT NULL   -- 'ok', 'failed'
);
```

---

## Summary

| Phase | Layer | Replaces / Adds | Target |
|-------|-------|-----------------|--------|
| 1 | Per-collection `meta.db` | `catalog.json` + `meta.json` | v0.5.8 |
| 2 | Global `catalog.db` | Filesystem walk for listings | v0.6 |
| 3 | Operational state | Tenant profiles, rate limits, log retention | v0.7–v0.8 |
| 4 | Governance | Versioning, audit, syndicates, usage, jobs | v0.8–v1.0 |
