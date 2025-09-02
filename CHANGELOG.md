## 0.5.5 — 2025-09-02

### Commits
- [buid] Add e2e check target and cleanup Makefile
- [build] Enhance startup scripts, add dependency clean Makefile target
- [core] Add CSV ingestion options: headers (yes|no), meta_cols and include_cols
- [core] Add default docid behavior so that vectors are seamlessly overriden when same file is ingested even if no docid is provided
- [core] Fixed txtai_store to handle indexes correctly and always return search text.
- [core] Fixing auth and adding tests
- [core] Normalize entry point config and add binding and auth safeguards for prod envs
- [core] Standardize request metrics in API and enable service metrics in service pipeline
- [pkg] Add docker targets and make further adjustments do Makefile
- [pkg] Add pypi publish makefile target
- [pkg] Fix dependencies: add sqlite4 to testing and explicitly add faiss-cpu to cpu-only target
- [store] Make sure FAISS indexes and dir structure are initialized upon collection creation.
- chore(release): v0.5.4
- chore: bump version to 0.5.5
- feat: initial public release of PatchVec — multi-tenant, pluggable vector search microservice
- Fix .gitlab-ci.yml file

---
## 0.5.4 — 2025-09-02

### Commits
- [buid] Add e2e check target and cleanup Makefile
- [build] Enhance startup scripts, add dependency clean Makefile target
- [core] Add CSV ingestion options: headers (yes|no), meta_cols and include_cols
- [core] Add default docid behavior so that vectors are seamlessly overriden when same file is ingested even if no docid is provided
- [core] Fixed txtai_store to handle indexes correctly and always return search text.
- [core] Fixing auth and adding tests
- [core] Normalize entry point config and add binding and auth safeguards for prod envs
- [core] Standardize request metrics in API and enable service metrics in service pipeline
- [pkg] Add docker targets and make further adjustments do Makefile
- [pkg] Add pypi publish makefile target
- [pkg] Fix dependencies: add sqlite4 to testing and explicitly add faiss-cpu to cpu-only target
- [store] Make sure FAISS indexes and dir structure are initialized upon collection creation.
- chore(release): v0.5.4
- feat: initial public release of PatchVec — multi-tenant, pluggable vector search microservice
- Fix .gitlab-ci.yml file

---
## 0.5.4 — 2025-08-12

### Commits
- feat: initial public release of PatchVec — multi-tenant, pluggable vector search microservice

---
# Changelog

## 0.5.3 — 2025-08-12

### Config
- Introduced minimal `.env.example` (required vars only; `PATCHVEC_` scheme)
- Clarified tenants secrets via untracked `tenants.yml`

### Packaging
- Added Makefile-based release flow (tests gate release; Docker/compose versions bumped automatically)
- Added Gitlab & Github CI/CD workflows (not tested)

### Docs
- Split README into **README.md** (end-user) and **CONTRIBUTING.md** (dev)
- Added REST examples with `curl`
- Documented uvicorn server overrides via `HOST`, `PORT`, `RELOAD`, `WORKERS`, `LOG_LEVEL`
- Trimmed Quickstart and added PyPI install path

---
## 0.5.2 — 2025-08-12

### Testing
- Added CSV and PDF ingestion/search
- Adjusted test cases for FastAPI’s stricter body/query validation.

### Arch
- Added `TxtaiEmbedder` as default; added `OpenAIEmbedder` and `SbertEmbedder`.

### API
- Fixed `POST /search` route to accept `SearchBody` via JSON body.

### Other
- Added `docker-composer` stub

---
## 0.5.1 — 2025-08-11

### Testing
- Added comprehensive pytest test suite covering:
  - Collection creation/deletion
  - Document ingestion & search (TXT)
  - Re-ingestion with purge
- Expanded pytest coverage for TXT ingestion, re-ingestion, and search.
- Fixed relative import issues in tests.

### Arch
- Refactored store and embedder factories to use Python 3.10+ `match` syntax.
- Standardized naming (`*_store`, `*_emb`).

### Auth
- Refactored authentication/authorization into `auth_ctx()` and `authorize_tenant()` using FastAPI dependency injection.
- Authorization now automatically derives tenant from bearer token when applicable.

### API
- Unified GET and POST search behavior.

---
## 0.5 — 2025-08-11

### Testing
- Added `DummyStore` for testing.

### Arch
- Isolated vector store interfaces via ABC (`BaseStore`) for plug-in stores (Qdrant, FAISS, etc.).
- Added `StoreFactory` and `EmbedderFactory` with runtime store/embedder selection (pluggable backends).

### API
- Added `/health` endpoint with general metrics and alive status

---
## 0.4 — 2025-08-10
- Modularized codebase:
  - `stores/` for vector store backends.
  - `embedders/` for embedding backends.
  - `auth.py` for authentication/authorization implementation.
  - `service.py` for main logic implementation (abstracted from api and cli interfaces).
  - `cli.py` for cli implementation.
  - `main.py` for endpoint routing and default initialization.
  - `preprocess.py` for file ingestion helpers.
  - `metrics.py` for metrics implementation.

---
## 0.3 — 2025-08-09
- Added QdrantStore skeleton (methods unimplemented).
- Added `OpenAIEmbedder` proof of concept (not tested).
- Introduced `CFG` for unified cfg management.
- Added complete cli mode

---
## 0.2 — 2025-08-08
- Implemented multi-tenant routing (`/{tenant}/{collection}`).
- Added basic static authentication via global or per-tenant API keys.
- Added document ingestion and collection management endpoints.

---
## 0.1 — 2025-08-07
- First working prototype with:
  - FastAPI service with search endpoint.
  - FAISS store and Sbel embeddings.
  - Command-line TXT ingestion and REST `search` endpoint.
  - Single-tenant mode.
  - Minimal auth stub.
