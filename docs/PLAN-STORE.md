<!-- (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# STORE-PLAN — Store Layer Separation

PatchVec's store architecture was designed from day one as a
layered system: embedder, vector index, metadata store, and
service logic are independent concerns with typed contracts
between them. The codebase already reflects this — `BaseStore`
ABC, `BaseEmbedder` ABC, `CollectionDB`, the embedder factory,
`SearchResult` dataclass, and the service/store boundary have
been in place since early versions. Each was shipped
incrementally as the product matured.

What this plan addresses is the final step: replacing the txtai
dependency — which was the right bootstrapping choice — with
PatchVec's own FAISS backend and activating the embedder layer
that has been waiting in the wings. The seams are already cut.
This plan connects them.

---

## Motivation

`TxtaiStore` (950+ lines) conflates four concerns:

1. **Vector engine** — `_emb` dict of `TxtaiVectorBackend` objects
   (wrapping `txtai.Embeddings`: FAISS index I/O, `em.search()`,
   `em.upsert()`, `em.delete()`).
2. **Metadata store** — `_dbs` dict of `CollectionDB` objects
   (Phase 1 SQLite, already separated in `pave/meta_store.py` but
   lifecycle managed by `TxtaiStore`).
3. **Catalog** — `list_tenants()`, `list_collections()`,
   `catalog_metrics()` via filesystem walks.
4. **Embedding model management** — `_models` shared cache,
   `_config()` reads global model from config. No per-collection
   model support.

PatchVec already re-implements most of what txtai provides on top
of txtai:

| Concern | txtai owns | PatchVec re-owns |
|---------|-----------|-----------------|
| Metadata store | internal SQLite | CollectionDB |
| Chunk text | content store | sidecars |
| Model cache | `Embeddings(models=)` | `_models` dict |
| Filter/query | SQL `similar()` | `_build_sql`, `_split_filters` |
| ID management | txtai internal | `docid::chunk_id` convention |

txtai adds ~150 MB of install weight for what is effectively a FAISS
`index.search(vector, k)` call. Replacing txtai with raw FAISS +
`sentence-transformers` (both already transitive deps of txtai)
eliminates the duplication and gives PatchVec full ownership of the
stack.

`BaseStore` ABC forces any new vector backend to re-implement all
four concerns. `QdrantStore` is a stub precisely because the surface
is too large.

`service.py` breaks the abstraction: `_unwrap_store()` reaches
through `SpyStore` wrappers, `_flush_store_caches()` clears `_dbs`
and `_emb` dicts directly, `_lock_indexes()` imports
txtai_store's module-level lock registry. Archive ops are scattered
between service and store.

The embedder factory (`pave/embedders/`) exists but is dead code —
never called by `TxtaiStore`, which creates its own `Embeddings`
internally.

Per-collection embeddings (P1-32) is impossible without resolving
this: the model spec must be stored per-collection, the factory
must create the right embedder, and the vector backend must index
pre-computed vectors.

---

## Layer contracts

Five interfaces define PatchVec's store stack. Each layer has a
single responsibility and communicates with its neighbours through
a typed contract. No layer bypasses another.

### 1. Embedder — text → vectors

Converts a batch of texts into embedding vectors. Does not know
about collections, tenants, metadata, or storage.

```python
# pave/embedders/base.py
class Embedder(Protocol):
    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        """Encode texts into a (N, dim) matrix of unit vectors."""
        ...
    @property
    def dimension(self) -> int:
        """Embedding dimensionality (e.g. 384)."""
        ...
```

Existing implementations (currently dead code, to be activated):

| Class | Module | Backend |
|-------|--------|---------|
| `SbertEmbedder` | `pave/embedders/sbert_emb.py` | sentence-transformers |
| `OpenAIEmbedder` | `pave/embedders/openai_emb.py` | OpenAI API |
| `TxtaiEmbedder` | `pave/embedders/txtai_emb.py` | txtai (transitional) |

Factory: `get_embedder()` in `pave/embedders/factory.py` dispatches
on `embedder.type` config key. Already written.

**Return type change**: current `encode()` returns
`list[list[float]]`. Must change to `NDArray[np.float32]` —
FAISS needs numpy, and the `.tolist()` round-trip is wasteful.

**`dim` → `dimension`**: current property is `dim: int | None`.
Must become `dimension: int` (non-optional; FAISS index creation
requires it at construction time).

### 2. VectorBackend — vectors → (rid, score) pairs

Stores vectors keyed by string record ID. Searches by vector
similarity. Does not know about text, metadata, or embedders.
Persistence location/connection details are backend-specific and
passed via constructor keys (not via generic path parameters).

```python
# pave/backends/base.py
class VectorBackend(Protocol):
    def initialize(self) -> None:
        """Load/prepare backend state from its own constructor settings."""
        ...
    def add(
        self, rids: list[str], vectors: NDArray[np.float32],
    ) -> None:
        """Add vectors with associated record IDs."""
        ...
    def search(
        self, vector: NDArray[np.float32], k: int,
    ) -> list[tuple[str, float]]:
        """Return up to k (rid, score) pairs, descending."""
        ...
    def delete(self, rids: list[str]) -> None:
        """Remove vectors by record ID."""
        ...
    def flush(self) -> None:
        """Persist pending state (local backends) or no-op (remote backends)."""
        ...
    def close(self) -> None:
        """Release backend resources."""
        ...
```

### 3. CollectionDB — metadata storage + filtered queries

Per-collection SQLite store. Owns two representations of the
same metadata: `meta_json` (denormalized, for retrieval) and
`chunk_meta` k/v table (normalized, for filtered queries).

Existing contract (`pave/meta_store.py`, Phase 1 — unchanged):
- `upsert_chunks(docid, chunks, doc_meta)` — write
- `delete_doc(docid)` — write
- `has_doc(docid)` — read
- `get_meta_batch(rids)` — read (bulk metadata retrieval)
- `get_doc_chunk_counts()` — read (catalog metrics)

New in Step 3:
- capability-based filter pushdown entrypoint (backend/local helper)
  for candidate reduction before canonical post-filter.

### 4. Store orchestrator — composes all layers

Single entry point for service.py. Owns concurrency
(`collection_lock`), the encode→search→filter→hydrate pipeline,
backend + CollectionDB lifecycle, and archive I/O.

**Contract to service.py** (text in, typed results out):

```
service.py calls          Store does internally
─────────────────         ────────────────────
index_records(            embedder.encode(texts)
  tenant, coll, docid,    backend.add(rids, vectors)
  records, doc_meta)      col_db.upsert_chunks(...)

search(                   embedder.encode([query])
  tenant, coll,           backend.search(vector, k*5)
  query, k, filters)      col_db.filter_rids(...)
                          col_db.get_meta_batch(...)
                          → list[SearchResult]

purge_doc(...)            col_db.delete_doc(docid)
                          backend.delete(rids)
```

service.py never sees vectors, embedders, or backends. It passes
text and gets `SearchResult` / `dict` back — same contract as
today's `BaseStore`.

### 5. service.py — business logic + error shaping

Owns: docid generation, re-ingest (purge + ingest), response
envelopes (`{"ok": true, ...}`), error codes, metrics counters,
latency measurement, ops logging.

Does NOT own: encoding, vector search, metadata storage,
concurrency, archive mechanics.

Contract to routes: `dict[str, Any]` responses (or `ServiceError`
for search). Routes convert to HTTP status codes.

---

## Target architecture

```
Embedder          ──→  encode(texts) → vectors
                                │
                                ▼
FaissBackend      ──→  add(rids, vectors) / search(vector, k)
                                │
                                ▼
CollectionDB      ──→  filter by k/v metadata
                       hydrate results with meta_json
                                │
                                ▼
Store orchestrator ──→  compose all layers, own concurrency
```

- **Embedder and VectorBackend are separate concerns.** The embedder
  converts text → vectors. The backend stores and searches vectors.
  Neither knows about the other.
- **CollectionDB owns both metadata retrieval (JSON) and metadata
  filtering (k/v table).** No more txtai SQL queries for filtering.
- **Single vector backend type per instance.** Mixed backends per
  instance is a 2.0+ concern.
- **Per-collection embedder config** stored in `GlobalDB` (Phase 2
  SQLite, future step).
- **`Store` orchestrator** composes all layers, owns concurrency
  (`collection_lock`), the search-then-hydrate pattern, and archive
  I/O.
- **`service.py`** talks only to `Store`; no more `_unwrap_store`
  or `_flush_store_caches`.
- **External API unchanged.**

---

## Step 1 — VectorBackend protocol (v0.5.9) ✓ DONE

Extracted `VectorBackend` + `TxtaiVectorBackend` under
`pave/backends/` and moved `TxtaiStore._emb` to that seam.

---

## Step 2 — Clean VectorBackend protocol + FaissBackend (v0.5.9)

### Problem

Step 2 completes `P1-29b`: finalize vector-native backend flow with
`FaissBackend` and activate embedder wiring.

### File layout

Backends live in `pave/backends/`, embedders in `pave/embedders/`.
Current state and target end-state are:

```
pave/backends/
    __init__.py          # re-exports backend contracts/adapters
    base.py              # VectorBackend protocol
    txtai.py             # TxtaiVectorBackend
    qdrant.py            # QdrantVectorBackend (stub)
    faiss.py             # FaissBackend
pave/embedders/
    __init__.py          # re-exports Embedder, get_embedder
    base.py              # Embedder protocol
    sbert_emb.py         # SentenceTransformer implementation
```

`pave/vector_backend.py` is retired once `pave/backends/` is wired in.

### Protocols

`VectorBackend` and `Embedder` protocols are defined in the
**Layer contracts** section above. Step 2 implements them.

### FaissBackend

```python
# pave/backends/faiss.py
class FaissBackend:
    """Raw FAISS index with string ID mapping."""
    def __init__(self, dimension: int, *, storage_dir: Path) -> None:
        # IndexFlatIP for cosine sim (normalized vectors)
        self._index = faiss.IndexIDMap2(
            faiss.IndexFlatIP(dimension)
        )
        self._rid_to_id: dict[str, int] = {}
        self._id_to_rid: dict[int, str] = {}
        self._next_id: int = 0
        self._storage_dir = storage_dir

    def add(self, rids, vectors) -> None: ...
    def search(self, vector, k) -> ...: ...
    def delete(self, rids) -> None: ...
    def initialize(self) -> None: ...
    def flush(self) -> None: ...  # faiss.write_index + id map in storage_dir
    def close(self) -> None: ...
```

Remote backends receive service coordinates instead of filesystem paths:

```python
class QdrantBackend:
    def __init__(self, *, url: str, collection: str, api_key: str | None = None):
        ...
```

### Files changed

| File | Change |
|------|--------|
| `pave/backends/` | New package: protocol + txtai adapter + qdrant stub |
| `pave/embedders/` | Existing package retained; activation under Step 2 |
| `pave/vector_backend.py` | Retired (moved to `pave/backends/txtai.py`) |
| `pave/stores/txtai_store.py` | Import path + backend wrapper wiring |

### What does NOT change

`BaseStore`, `service.py`, `CollectionDB`, external API.

### Step 2 benchmark results

Benchmarked on the same machine and parameters as PLAN-SQLITE
Phase 1 (latency: 1200 queries / concurrency=42, stress: 90s /
concurrency=8). Baseline is the last txtai-backed commit
(`a52c9fe`); "after" is the FaissBackend cutover (`fc52178` /
`30f4a53`).

**Latency benchmark** — 1200 queries, concurrency=42

| | Min | p50 | p95 | p99 | Max | Throughput |
|--|-----|-----|-----|-----|-----|------------|
| before\_faiss (txtai) | 309ms | 1029ms | 1071ms | 1096ms | 1361ms | 39.4 ops/s |
| after\_faiss ✓ | **80ms** | **641ms** | **894ms** | **949ms** | **958ms** | **60.1 ops/s** |
| Δ | −74% | −38% | −17% | −13% | −30% | **+53%** |

**Stress benchmark** — 90s duration, concurrency=8

| | Total ops | Throughput | Total err% | Search p50 | Search p95 | Search p99 |
|--|-----------|------------|------------|------------|------------|------------|
| before\_faiss | 1499 | 16.5 ops/s | 0.0% | 139ms | 1567ms | 2552ms |
| after\_faiss ✓ | **2678** | **29.6 ops/s** | **0.0%** | **102ms** | **860ms** | **1339ms** |
| Δ | +79% | **+79%** | — | −27% | **−45%** | **−48%** |

Stress per-operation highlights (p50 / p95):

| Operation | before\_faiss | after\_faiss | Δ p50 | Δ p95 |
|-----------|--------------|-------------|-------|-------|
| search | 139 / 1567ms | 102 / 860ms | −27% | −45% |
| collection\_create | 335 / 458ms | 19 / 36ms | −94% | −92% |
| ingest\_small | 172 / 1448ms | 117 / 795ms | −32% | −45% |
| ingest\_chunked | 1976 / 3217ms | 1009 / 1920ms | −49% | −40% |
| health | 7 / 503ms | 7 / 19ms | — | −96% |

**Result files**:

- [latency-2026-03-08_225319_before_faiss-a52c9fe.txt](../benchmarks/results/latency-2026-03-08_225319_before_faiss-a52c9fe.txt)
- [stress-2026-03-08_225319_before_faiss-a52c9fe.txt](../benchmarks/results/stress-2026-03-08_225319_before_faiss-a52c9fe.txt)
- [latency-2026-03-09_033453_after_faiss-fc52178.txt](../benchmarks/results/latency-2026-03-09_033453_after_faiss-fc52178.txt)
- [stress-2026-03-09_033453_after_faiss-30f4a53.txt](../benchmarks/results/stress-2026-03-09_033453_after_faiss-30f4a53.txt)

**Analysis**:

The FAISS cutover eliminates txtai's query-compilation and
internal SQLite overhead on every search. The biggest wins are:

- **collection\_create** drops from ~335ms to ~19ms (−94%). txtai
  was eagerly loading the embedding model and initializing its
  own internal SQLite on every `load_or_init`; FaissBackend only
  allocates an empty FAISS index (CollectionDB still creates its
  tables, but that is fast).
- **Search throughput** jumps 53% (latency) / 79% (stress). The
  raw FAISS `index.search()` call avoids txtai's SQL parsing,
  content-store round-trip, and Python-side result
  deserialization.
- **health p95** drops from 503ms to 19ms. The health probe calls
  `load_or_init("_system", "health")` — same collection-create
  path, same speedup.
- **Tail latency** improves across the board: search p99 drops
  48% under mixed load. Ingest p50 drops 32-49% because FAISS
  `add_with_ids` is cheaper than txtai's `upsert` pipeline.

Similarity scores are slightly lower (e.g. doc1 top hit 0.836 →
0.697) because txtai applies internal re-normalization that raw
FAISS with `IndexFlatIP` does not. Ranking order is preserved.
This is expected and acceptable — the score magnitudes are
backend-specific; what matters is relative ordering.

Zero errors in both runs.

---

## Step 3 — CollectionDB k/v metadata for filtering (v0.5.9)

### Problem

With txtai removed, metadata filtering can no longer piggyback on
txtai's SQL `WHERE` clauses. Filtering from `meta_json` (JSON
blobs) requires parsing every candidate — too slow for large
result sets.

### Solution

Add a `chunk_meta` k/v table alongside the existing `meta_json`
column. Both are written at ingest time from the same dict.
`meta_json` is the source of truth for full metadata retrieval.
`chunk_meta` is the first local pushdown index for fast candidate
reduction. Pushdown itself is capability-based per backend.

```sql
-- CollectionDB migration 2
CREATE TABLE chunk_meta (
    rid   TEXT NOT NULL,
    key   TEXT NOT NULL,
    value TEXT NOT NULL
);
CREATE INDEX chunk_meta_rid ON chunk_meta (rid);
CREATE INDEX chunk_meta_kv ON chunk_meta (key, value);
```

### Filter flow (post-txtai, capability-based)

1. `FaissBackend.search(vector, k*5)` → candidate `(rid, score)`
   pairs (overfetch).
2. Pushdown phase (optional, capability-based): backend (or a local
   helper such as CollectionDB) receives full filters and applies what
   it supports. CollectionDB SQL on `chunk_meta` is the first concrete
   implementation (`lang='en'`, negation, etc.).
3. Canonical post-filter (Python): `_matches_filters()` runs on
   survivors to enforce consistent semantics across all backends.
4. Truncate to k, hydrate from `meta_json`.

Exact-match and negation are expected to be the first pushdown wins.
Wildcards/comparison/date ops can remain in post-filter until a backend
adds compatible pushdown support.

### Files changed

| File | Change |
|------|--------|
| `pave/meta_store.py` | Migration 2: `chunk_meta` + `filter_by_meta` |
| `pave/stores/txtai_store.py` | Add pushdown handoff + canonical post-filter |

### What does NOT change

`_matches_filters()` remains canonical for correctness.
Pushdown is an optimization layer. `_sanit_sql`, `_sanit_field`,
`_sanit_meta_dict` stay (input sanitization is always needed).

### Step 3 benchmark results

Benchmarked on the same machine and benchmark harness before and
after the `chunk_meta` pushdown change. Baseline is the canonical
`before_metakvtable` result set captured from `b971101` and saved
on branch `before-metakvtable-benchresults` (`29a5e32`). "After"
is the post-Step-3 run tagged `11becc6`. Parameters: latency
5000 queries / concurrency=42.

No canonical before/after stress pair was captured for Step 3, so
only the latency benchmark is reported here.

**Latency benchmark** — 5000 queries, concurrency=42

| Variant | Run | p50 | p95 | p99 | Throughput |
|---------|-----|-----|-----|-----|------------|
| search | before\_metakvtable | 720ms | 897ms | 1233ms | 55.5 ops/s |
| search | after\_metakvtable ✓ | **699ms** | **720ms** | **775ms** | **59.7 ops/s** |
| search | Δ | −3% | −20% | −37% | **+8%** |
| search\_exact | before\_metakvtable | 892ms | 1212ms | 1474ms | 45.6 ops/s |
| search\_exact | after\_metakvtable ✓ | **700ms** | **758ms** | **889ms** | **59.0 ops/s** |
| search\_exact | Δ | **−22%** | **−37%** | **−40%** | **+29%** |
| search\_wildcard | before\_metakvtable | 704ms | **740ms** | **883ms** | 58.8 ops/s |
| search\_wildcard | after\_metakvtable | **701ms** | 749ms | 902ms | **58.9 ops/s** |
| search\_wildcard | Δ | ≈0% | +1% | +2% | ≈0% |
| search\_mixed | before\_metakvtable | **688ms** | **711ms** | 856ms | **60.3 ops/s** |
| search\_mixed | after\_metakvtable | 690ms | 719ms | **848ms** | 60.1 ops/s |
| search\_mixed | Δ | ≈0% | +1% | −1% | ≈0% |

**Result files**:

- [latency-2026-03-09_230807_before_metakvtable-b971101-none.txt](../benchmarks/results/latency-2026-03-09_230807_before_metakvtable-b971101-none.txt)
- [latency-2026-03-09_230807_before_metakvtable-b971101-exact.txt](../benchmarks/results/latency-2026-03-09_230807_before_metakvtable-b971101-exact.txt)
- [latency-2026-03-09_230807_before_metakvtable-b971101-wildcard.txt](../benchmarks/results/latency-2026-03-09_230807_before_metakvtable-b971101-wildcard.txt)
- [latency-2026-03-09_230807_before_metakvtable-b971101-mixed.txt](../benchmarks/results/latency-2026-03-09_230807_before_metakvtable-b971101-mixed.txt)
- [latency-2026-03-10_194207_after_metakvtable-11becc6-none.txt](../benchmarks/results/latency-2026-03-10_194207_after_metakvtable-11becc6-none.txt)
- [latency-2026-03-10_194207_after_metakvtable-11becc6-exact.txt](../benchmarks/results/latency-2026-03-10_194207_after_metakvtable-11becc6-exact.txt)
- [latency-2026-03-10_194207_after_metakvtable-11becc6-wildcard.txt](../benchmarks/results/latency-2026-03-10_194207_after_metakvtable-11becc6-wildcard.txt)
- [latency-2026-03-10_194207_after_metakvtable-11becc6-mixed.txt](../benchmarks/results/latency-2026-03-10_194207_after_metakvtable-11becc6-mixed.txt)

**Analysis**:

- **Exact-match filtering is the clear Step 3 win.** `search_exact`
  improves 22% at p50, 37% at p95, 40% at p99, and 29% in
  throughput. This is the direct target of `chunk_meta`
  pushdown.
- **Wildcard stays effectively flat**, which is expected because
  wildcard filters are still handled by the canonical Python
  post-filter, not by `CollectionDB.filter_by_meta()`.
- **Mixed filters are effectively neutral**: only the exact subset
  of a mixed filter can be pushed down, so the benchmark shows a
  small tail win but no material movement in p50/p95 or
  throughput.
- **No parity drift was observed**. Hit counts are identical before
  and after in every variant (`25000`, `16000`, `16000`, `6000`)
  and error rate remains `0.0%`.
- **Plain `search` also improves in this pair of runs**, but that
  path does not use pushdown; treat it as background run-to-run
  variance or incidental system-state improvement, not as a Step 3
  effect.

---

## Step 4 — Store orchestrator (v0.5.9)

### Problem

`service.py` breaks encapsulation with `_unwrap_store()`,
`_flush_store_caches()`, and `_lock_indexes()`. Archive operations
are scattered between service and store. There is no single
component that coordinates vector backend + embedder + metadata +
catalog + concurrency.

### Interface

```python
# pave/store.py (new — the orchestrator)
class Store:
    def __init__(
        self,
        data_dir: str,
        embedder: Embedder,
        backend_factory: Callable[[int], VectorBackend],
    ) -> None: ...

    # Collection lifecycle
    def create_collection(self, tenant, name): ...
    def delete_collection(self, tenant, name): ...
    def rename_collection(self, tenant, old, new): ...
    def list_tenants(self) -> list[str]: ...
    def list_collections(self, tenant) -> list[str]: ...
    def catalog_metrics(self) -> dict[str, int]: ...

    # Document ops (coordinates embedder + backend + CollectionDB)
    def has_doc(self, tenant, collection, docid) -> bool: ...
    def purge_doc(self, tenant, collection, docid) -> int: ...
    def index_records(self, tenant, collection, docid,
                      records, doc_meta): ...
    def search(self, tenant, collection, query, k,
               filters) -> list[SearchResult]: ...

    # Cache management
    def flush_caches(self) -> None: ...
```

### Orchestrated search flow

The encode→search→filter→hydrate pipeline is documented in the
**Layer contracts § Store orchestrator** section above.

Key concurrency detail: FAISS search runs inside
`collection_lock`; metadata reads (WAL) run outside it — same
pattern as today's `TxtaiStore.search()`.

### Where things move

| Concern | From | To |
|---------|------|----|
| `collection_lock` registry | `txtai_store.py` module scope | `Store` instance |
| `_flush_store_caches` | `service.py` | `Store.flush_caches()` |
| `_lock_indexes` | `service.py` | `Store._lock_all_indexes()` |
| `_unwrap_store` | `service.py` | deleted |
| archive mechanics | `service.py` | `Store` methods |
| listing | `TxtaiStore` | `Store` (filesystem or `GlobalDB`) |
| chunk text sidecars | `TxtaiStore` | `Store` |
| filter logic | `TxtaiStore` | `pave/filters.py` + `CollectionDB` |

### What `TxtaiStore` becomes

Deleted. `FaissBackend` + `SentenceTransformerEmbedder` +
`CollectionDB` + `Store` orchestrator replace it entirely.

### `BaseStore` becomes the orchestrator interface

`BaseStore` is redefined (or replaced by `StoreProtocol`) with
the `Store` signature above. Signature changes:
- `list_tenants(data_dir)` → `list_tenants()` (data_dir known)
- `catalog_metrics(data_dir)` → `catalog_metrics()`
- `load_or_init`, `save` become internal
- `search` takes `query: str` (orchestrator calls embedder)

### Files changed

| File | Change |
|------|--------|
| `pave/store.py` | New — `Store` orchestrator |
| `pave/filters.py` | New — `split_filters`, `matches_filters`, `_sanit_*` extracted |
| `pave/stores/txtai_store.py` | Deleted; replaced by orchestrator + backends |
| `pave/stores/base.py` | Redefined as orchestrator interface |
| `pave/service.py` | Remove store internals; archive ops delegate to `store` |
| `pave/main.py` | Minor — construct `Store` with `FaissBackend` + embedder |
| tests | `SpyStore` updated; `DummyStore` rebuilt or retired |

---

## Step 5 — GlobalDB + catalog separation (owned by PLAN-SQLITE)

This step is specified in `docs/PLAN-SQLITE.md` (Phase 2) and
tracked as roadmap item `P1-33`.

`PLAN-STORE` treats Step 5 as an external dependency:
- `GlobalDB` becomes the source of truth for listing/catalog.
- `get_collection_config()` provides per-collection embedder
  config.
- `Store` orchestrator integrates that interface.

---

## Step 6 — Per-collection embeddings (v0.6, resolves P1-32)

### Problem

All collections use the same embedding model. Per-collection
model config is a hard requirement for multi-model deployments.

### How it works

With the orchestrator (Step 4) and `GlobalDB` (Step 5) in place:

1. `create_collection(tenant, name, embed_model="...")` stores
   model spec in `GlobalDB.collections.embed_model`.
2. `_load_or_init` reads `embed_model` from `GlobalDB`, calls
   `embedder_factory.get(model_spec)` to resolve the model,
   creates `FaissBackend` with the right dimension.
3. Collections without explicit `embed_model` use the instance
   default.
4. The embedder factory caches model instances — collections
   sharing a model share the embedder.

### Validation

- Reject search across collections with incompatible embeddings
  (dimensionality mismatch).
- `embed_model` is immutable after creation (changing it
  invalidates all stored vectors). Re-embedding requires delete
  + recreate.

---

## Migration from txtai indexes

Existing indexes are in txtai's format (FAISS index + txtai
internal SQLite). Two migration paths:

**A) Re-index from chunk text sidecars (recommended).** PatchVec
already persists chunk text as sidecar `.txt` files. A migration
tool reads sidecars + `CollectionDB` metadata, encodes via
`SentenceTransformerEmbedder`, writes to `FaissBackend`. No data
loss. Simple, robust.

**B) Extract vectors from txtai index.** Load the txtai index,
read all vectors + IDs, write to `FaissBackend` format. Faster
(no re-encoding) but depends on txtai's internal format.

Path A is preferred — it's independent of txtai and validates the
entire pipeline end-to-end.

A `pavecli migrate-index` command handles the conversion. The
server detects txtai-format indexes on startup and warns (does
not auto-migrate).

---

## Dependency graph

```
Step 1  VectorBackend protocol (v0.5.9) ✓
  │
  └──→ Step 2  Clean protocol + FaissBackend + Embedder (v0.5.9)
         │
         └──→ Step 3  CollectionDB k/v metadata (v0.5.9)
                │
                └──→ Step 4  Store orchestrator (v0.5.9)
                       │
                       ├──→ Step 5  GlobalDB (PLAN-SQLITE P2)
                       │
                       └──→ Step 6  Per-collection embeddings
```

Steps 2 and 3 are independent (parallel branches). Step 4
integrates both. Steps 5 and 6 are features enabled by Step 4.

---

## ROADMAP amendments

Store-plan-owned items (revised):

| ID | Task | Effort | Version | Depends on |
|----|------|--------|---------|------------|
| P1-29 | ~~Extract VectorBackend protocol~~ | 🔧 | v0.5.9 | — |
| P1-29b | Clean protocol + FaissBackend + Embedder | 🔧 | v0.5.9 | P1-29 |
| P1-29c | CollectionDB k/v metadata for filtering | 🔧 | v0.5.9 | — |
| P1-30 | ~~Activate embedder factory + model caching~~ | — | — | superseded by P1-29b |
| P1-31 | Store orchestrator | 🧱 | v0.5.9 | P1-29b, P1-29c |
| P1-32 | Per-collection embeddings | 🧱 | v0.6 | P1-31, P1-33 |

Existing items affected:
- **P1-33** (GlobalDB + catalog separation) owned by PLAN-SQLITE.
- **P3-26** (embedder/store contract) resolved by Steps 2-4.
- **P1-30** superseded — embedder extraction is part of Step 2.

---

## Risks

1. **Migration friction**: Existing txtai indexes require
   re-indexing. Mitigated by `pavecli migrate-index` and the fact
   that chunk text sidecars guarantee no data loss.

2. **Test monkeypatching**: Tests monkeypatch
   `TxtaiVectorBackend` at module level. After Step 2, the target
   changes to `FaissBackend`. Mechanical change, touches many test
   files.

3. **`_models` cache during flush**: `flush_caches()` must NOT
   clear the embedder model cache (models are expensive to load).
   Only backend instances and `CollectionDB` instances are flushed;
   the embedder survives.

4. **Filter performance**: The k/v table adds write overhead at
   ingest (one row per metadata key per chunk). Read performance
   is fast (indexed). Net positive for search-heavy workloads.

5. **FAISS delete support**: `IndexIDMap2` supports `remove_ids()`
   natively. `IndexIDMap` (without the 2) does not. Must use
   `IndexIDMap2`.

6. **Negation pre-filter path drift**: avoid backend-specific semantic
   drift by enforcing canonical post-filter after any pushdown.
