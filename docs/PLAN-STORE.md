<!-- (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# STORE-PLAN — Store Layer Separation Roadmap

PatchVec separates its monolithic `TxtaiStore` into composable layers:
a vector backend, an embedder factory, a metadata store, and a catalog.
A single orchestrator (`Store`) composes them and owns concurrency,
archive I/O, and the search-then-hydrate flow.

---

## Motivation

`TxtaiStore` (950+ lines) conflates four concerns:

1. **Vector engine** — `_emb` dict of txtai `Embeddings` objects (FAISS
   index I/O, `em.search()`, `em.upsert()`, `em.delete()`).
2. **Metadata store** — `_dbs` dict of `CollectionDB` objects (Phase 1
   SQLite, already cleanly separated in `pave/meta_store.py` but lifecycle
   managed by `TxtaiStore`).
3. **Catalog** — `list_tenants()`, `list_collections()`,
   `catalog_metrics()` via filesystem walks.
4. **Embedding model management** — `_models` shared cache, `_config()`
   reads global model from config. No per-collection model support.

`BaseStore` ABC forces any new vector backend to re-implement all four.
`QdrantStore` is a stub precisely because the surface is too large.

`service.py` breaks the abstraction: `_unwrap_store()` reaches through
`SpyStore` wrappers, `_flush_store_caches()` clears `_dbs` and `_emb`
dicts directly, `_lock_indexes()` imports txtai_store's module-level
lock registry. Archive ops are scattered between service and store.

The embedder factory (`pave/embedders/`) exists but is dead code — never
called by `TxtaiStore`, which creates its own `Embeddings` internally.

Per-collection embeddings (P1-10) is impossible without resolving
this: the model spec must be stored per-collection, the factory must
create the right embedder, and the vector backend must index pre-computed
vectors or be configured per-collection.

---

## Target architecture

```
GlobalDB  ──→  "collection X uses model Y"
                        │
                        ▼
EmbedderFactory  ──→  load/cache model Y  ──→  encode(text) → vector
                                                      │
                                                      ▼
VectorBackend   ──→  index(rids, vectors) / search(vector, k)
                                                      │
                                                      ▼
CollectionDB    ──→  hydrate results with metadata
```

- **Single vector backend type per instance.** Mixed backends per instance
  is a 2.0+ concern; the factory interface does not preclude it.
- **Per-collection embedder config** stored in `GlobalDB` (Phase 2 SQLite).
- **`Store` orchestrator** composes all four layers, owns concurrency
  (`collection_lock`), the search-then-hydrate pattern, and archive I/O.
- **`service.py`** talks only to `Store`; no more `_unwrap_store` or
  `_flush_store_caches`.
- **External API unchanged.**

---

## Step 1 — VectorBackend protocol (v0.5.9)

### Problem

`TxtaiStore` constructs and manages `txtai.Embeddings` objects directly.
No seam exists between "use the index" and "manage everything else."

### Interface

```python
# pave/vector_backend.py (new)
from typing import Protocol, Any

class VectorBackend(Protocol):
    def index(self, records: list[tuple[str, dict, str]]) -> None: ...
    def search(self, sql: str) -> list[dict[str, Any]]: ...
    def delete(self, rids: list[str]) -> None: ...
    def save(self, path: str) -> None: ...
    def load(self, path: str) -> None: ...
    def lookup(self, rids: list[str]) -> dict[str, Any]: ...
```

`TxtaiVectorBackend` wraps `txtai.Embeddings` — delegates all calls.
The `search(sql)` signature is txtai-flavored (accepts SQL strings
with `similar()` calls). Future non-txtai backends would use a
different dispatch; for now this is pragmatic and zero-risk.

### Files changed

| File | Change |
|------|--------|
| `pave/vector_backend.py` | New — protocol + `TxtaiVectorBackend` |
| `pave/stores/txtai_store.py` | `_emb` values become `VectorBackend`; `load_or_init` creates `TxtaiVectorBackend` instead of raw `Embeddings` |
| `tests/utils.py` | `FakeEmbeddings` satisfies `VectorBackend` protocol (or monkeypatch target adjusts) |

### What does NOT change

`BaseStore`, `service.py`, `CollectionDB`, `collection_lock`, external
API, filter system (`_build_sql` passes SQL to `backend.search()`).

---

## Step 2 — Embedder factory activation (v0.6, resolves P3-39)

### Problem

`pave/embedders/factory.py` and `BaseEmbedder` exist but are dead code.
`TxtaiStore._config()` hardcodes the model path from global config.
The `_models` dict (shared model cache) is owned by `TxtaiStore` but
conceptually belongs to the embedder layer.

### Interface

```python
# pave/embedders/factory.py (rewritten)
class EmbedderFactory:
    def __init__(self) -> None:
        self._cache: dict[str, BaseEmbedder] = {}
        self._models: dict = {}     # shared model objects for txtai

    def get(self, model_spec: str | None = None) -> BaseEmbedder:
        """Return embedder for model_spec; default from config if None.
        Caches by spec string — collections sharing a model share the
        instance."""
        ...

    @property
    def models(self) -> dict:
        """Shared model cache passed to TxtaiVectorBackend."""
        return self._models
```

### Key decision

For v0.6, `TxtaiVectorBackend` continues to use txtai's internal model
(txtai bundles model + index). The `EmbedderFactory` resolves the model
spec and owns the `_models` cache; `TxtaiVectorBackend` receives
`models=factory.models` at construction. Non-txtai backends would call
`embedder.encode()` directly.

### Files changed

| File | Change |
|------|--------|
| `pave/embedders/base.py` | Unchanged (already has the right shape) |
| `pave/embedders/factory.py` | Rewrite: `EmbedderFactory` class with caching |
| `pave/stores/txtai_store.py` | Constructor takes `EmbedderFactory`; `_models` comes from `factory.models`; `_config()` accepts `model_spec` param |
| `pave/stores/factory.py` | `get_store()` creates `EmbedderFactory`, passes to `TxtaiStore` |

### What does NOT change

`service.py`, `CollectionDB`, external API. Default behavior: global
model used when no per-collection spec exists (same as today).

### Note

Step 2 and Step 3 are independent — can be developed on parallel
branches.

---

## Step 3 — GlobalDB + catalog separation (v0.6, PLAN-SQLITE Phase 2)

### Problem

`list_tenants()` and `list_collections()` walk the filesystem.
`catalog_metrics()` opens temporary `CollectionDB` instances per
collection. This code belongs in a catalog layer, not in the vector
store.

Phase 2 of PLAN-SQLITE (`GlobalDB`) is the forcing function. When the
catalog moves to SQLite, listing code must be extracted from
`TxtaiStore`.

Additionally, `GlobalDB` is where per-collection `embed_model` is
stored, completing the foundation for P1-10.

### Interface

Already defined in `docs/PLAN-SQLITE.md` Phase 2. Key addition:

```python
class GlobalDB:
    ...
    def get_collection_config(
        self, tenant: str, name: str,
    ) -> dict[str, Any] | None:
        """Returns {embed_model, embed_config_json, ...} or None."""
        ...
```

### Files changed

| File | Change |
|------|--------|
| `pave/meta_store.py` | Add `GlobalDB` (schema, migrations, CRUD) |
| `pave/stores/txtai_store.py` | Remove `list_tenants()`, `list_collections()`, `catalog_metrics()` |
| `pave/stores/base.py` | Remove listing methods from `BaseStore` (move to orchestrator in Step 4) |

### What does NOT change

`CollectionDB`, vector backends, filter logic.

---

## Step 4 — Store orchestrator (v0.6)

### Problem

`service.py` breaks encapsulation with `_unwrap_store()`,
`_flush_store_caches()`, and `_lock_indexes()`. Archive operations are
scattered between service and store. There is no single component that
coordinates vector backend + metadata + catalog + concurrency.

### Interface

```python
# pave/store.py (new — the orchestrator)
class Store:
    def __init__(
        self,
        data_dir: str,
        vector_backend_factory: Callable[..., VectorBackend],
        embedder_factory: EmbedderFactory,
    ) -> None: ...

    # Collection lifecycle (delegates to GlobalDB)
    def create_collection(self, tenant, name, embed_model=None): ...
    def delete_collection(self, tenant, name): ...
    def rename_collection(self, tenant, old, new): ...
    def list_tenants(self) -> list[str]: ...
    def list_collections(self, tenant) -> list[str]: ...
    def catalog_metrics(self) -> dict[str, int]: ...

    # Document ops (coordinates backend + CollectionDB)
    def has_doc(self, tenant, collection, docid) -> bool: ...
    def purge_doc(self, tenant, collection, docid) -> int: ...
    def index_records(self, tenant, collection, docid, records): ...
    def search(self, tenant, collection, query, k, filters): ...

    # Archive I/O (low-level; service.py keeps the public interface)
    def flush_caches(self) -> None: ...
    def dump_archive(self) -> tuple[str, str | None]: ...
    def restore_archive(self, archive_bytes) -> dict: ...
```

### Where things move

| Concern | From | To |
|---------|------|----|
| `collection_lock` registry | `txtai_store.py` module scope | `Store` instance |
| `_flush_store_caches` | `service.py` | `Store.flush_caches()` |
| `_lock_indexes` | `service.py` | `Store._lock_all_indexes()` |
| `_unwrap_store` | `service.py` | deleted — no longer needed |
| `dump_archive` / `restore_archive` mechanics (lock, tar, extract) | `service.py` | `Store` methods; `service.py` keeps the public interface and any service-level concerns (error wrapping, response shaping) |
| listing (`list_tenants`, etc.) | `TxtaiStore` | `Store` via `GlobalDB` |
| chunk text sidecars | `TxtaiStore` | `Store` (or `pave/chunk_store.py`) |
| filter logic (`_build_sql`, etc.) | `TxtaiStore` | `pave/filters.py` |

### What `TxtaiStore` becomes

A thin factory that creates `TxtaiVectorBackend` instances. May be
renamed to `pave/stores/txtai_backend.py`. No lifecycle management,
no locking, no listing, no archive logic.

### `BaseStore` becomes the orchestrator interface

`BaseStore` is redefined (or replaced by `StoreProtocol`) with the
`Store` signature above. Signature changes:
- `list_tenants(data_dir)` → `list_tenants()` (data_dir known to orchestrator)
- `catalog_metrics(data_dir)` → `catalog_metrics()`
- `load_or_init`, `save` become internal (not exposed to `service.py`)

### Files changed

| File | Change |
|------|--------|
| `pave/store.py` | New — `Store` orchestrator |
| `pave/filters.py` | New — filter logic extracted from `TxtaiStore` |
| `pave/stores/txtai_store.py` | Drastically reduced; becomes backend factory |
| `pave/stores/base.py` | Redefined as orchestrator interface |
| `pave/service.py` | Remove `_unwrap_store`, `_flush_store_caches`, `_lock_indexes`; archive ops delegate to `store` |
| `pave/main.py` | Minor — `list_tenants` no longer passes `data_dir` |
| `tests/utils.py` | `SpyStore` updated; `DummyStore` rebuilt or retired |

---

## Step 5 — Per-collection embeddings (v0.6, resolves P1-10)

### Problem

All collections use the same embedding model. Per-collection model
config is a hard requirement for multi-model deployments.

### How it works

With the orchestrator (Step 4), `GlobalDB` (Step 3), and `EmbedderFactory`
(Step 2) in place:

1. `create_collection(tenant, name, embed_model="...")` stores model
   spec in `GlobalDB.collections.embed_model`.
2. `_load_or_init` reads `embed_model` from `GlobalDB`, calls
   `embedder_factory.get(model_spec)` to resolve the model, creates
   `TxtaiVectorBackend` with the right config.
3. Collections without explicit `embed_model` use the instance default.
4. The `EmbedderFactory` caches model instances — collections sharing a
   model share the embedder (and the `_models` dict for txtai).

### Validation

- Reject search across collections with incompatible embeddings
  (dimensionality mismatch).
- `embed_model` is immutable after creation (changing it invalidates all
  stored vectors). Re-embedding requires delete + recreate.

### Files changed

| File | Change |
|------|--------|
| `pave/store.py` | `create_collection` accepts `embed_model`; `_load_or_init` reads it from `GlobalDB` |
| `pave/meta_store.py` | `GlobalDB.register_collection` stores `embed_model` |
| `pave/service.py` | `create_collection` passes through `embed_model` |
| `pave/main.py` | `POST /collections/{tenant}/{name}` accepts optional `embed_model` |

---

## Dependency graph

```
Step 1  VectorBackend protocol (v0.5.9)
  │
  ├──→ Step 2  Embedder factory (v0.6) ───────┐
  │                                             │
  └──→ Step 3  GlobalDB + catalog (v0.6) ──────┤
                                                │
                                                ▼
                                        Step 4  Store orchestrator (v0.6)
                                                │
                                                ▼
                                        Step 5  Per-collection embeddings (v0.6)
```

Steps 2 and 3 are independent (parallel branches). Step 4 integrates
both. Step 5 is a feature enabled by Step 4.

---

## ROADMAP amendments

New items (P1-29 through P1-32, all new):

| ID | Task | Effort | Version | Depends on |
|----|------|--------|---------|------------|
| P1-29 | Extract VectorBackend protocol | 🔧 | v0.5.9 | — |
| P1-30 | Activate embedder factory + model caching | 🔧 | v0.6 | P1-29, P3-39 |
| P1-31 | Store orchestrator (compose backend + meta + catalog) | 🧱 | v0.6 | P1-29, P1-30, Phase 2 |
| P1-32 | Per-collection embeddings | 🧱 | v0.6 | P1-31 |

Existing items affected:
- **P3-39** (Resolve embedder factory integration): absorbed by P1-30.
- **P1-10** (Per-collection embeddings): renumbered/replaced by P1-32.
- **Phase 2 GlobalDB**: unchanged in PLAN-SQLITE.md; referenced by Step 3.

---

## Risks

1. **txtai SQL coupling**: `_build_sql` constructs txtai-specific SQL
   (`similar()` function). Stays as txtai-specific concern in
   `pave/filters.py`. Future non-txtai backends need a different query
   representation — the orchestrator would dispatch by backend type.

2. **Test monkeypatching**: Tests monkeypatch `Embeddings` at module
   level. After Step 1, the target changes to `TxtaiVectorBackend` or
   the factory callable. Mechanical change, touches many test files.

3. **`_models` cache during flush**: `flush_caches()` must NOT clear the
   model cache (models are expensive to load). Only backend instances and
   `CollectionDB` instances are flushed; the `EmbedderFactory` and its
   `_models` dict survive.

4. **Filter relocation**: `_build_sql`, `_split_filters`,
   `_matches_filters`, `_sanit_*` (~200 lines) move to `pave/filters.py`.
   Backend-specific (txtai SQL) but conceptually a query-building concern.
