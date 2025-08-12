# PatchVec — A lightweight, pluggable vector search microservice.

Upload → chunk → index (with metadata) → search via REST and CLI.

## Highlights
- Multi-tenant collections: `/collections/{tenant}/{name}`
- Upload and search **TXT**, **CSV**, and **PDF**
- Chunking per format:
  - PDF → 1 chunk/page
  - TXT → configurable chunk size + overlap
  - CSV → 1 chunk/row
- Metadata filters on POST search (`{"filters": {"docid": "DOC-1"}}`)
- Health, metrics, and Prometheus endpoints
- Configurable auth modes: `none` or `static` (Bearer)
- Default backends are local (vendor-neutral "default"); embedders & stores are pluggable

## Requirements
- Python 3.10+

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install patchvec
```

> CPU-only by default. If you have a CUDA setup and want GPU-accelerated deps, install the GPU-enabled packages in your environment before running PatchVec.

## Quickstart
```bash
# Start the server (installed entry point)
pavesrv

# Or run with uvicorn manually if you prefer:
uvicorn pave.main:app --host 0.0.0.0 --port 8080
```

## Minimal config (optional)
By default PatchVec runs with sensible local defaults. To customize, create `config.yml` and set:
```yaml
vector_store:
  type: default
embedder:
  type: default
auth:
  mode: none    # or 'static' with per-tenant Bearer keys
```
Then export:
```bash
export PATCHVEC_CONFIG=./config.yml
```

## REST example
```bash
# Create a collection
curl -X POST http://localhost:8080/collections/acme/docs

# Upload a TXT document
curl -X POST http://localhost:8080/collections/acme/docs/documents   -F "file=@sample.txt" -F "docid=DOC1"

# Search (GET, no filters)
curl -G --data-urlencode "q=hello" http://localhost:8080/collections/acme/docs/search

# Search (POST, with filters)
curl -X POST http://localhost:8080/collections/acme/docs/search   -H "Content-Type: application/json"   -d '{"q":"hello","k":5,"filters":{"docid":"DOC1"}}'
```

## License
GPL-3.0-or-later — (C) 2025 Rodrigo Rodrigues da Silva
