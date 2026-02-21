<!-- (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net> -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# PatchVec — A lightweight, pluggable vector search microservice.

Upload → chunk → index (with metadata) → search via REST and CLI.

## Highlights
- Multi-tenant collections: `/collections/{tenant}/{name}`
- Upload and search TXT, CSV, and PDF
- Deterministic provenance: every hit returns doc id, page, offset, snippet
- Metadata filters on search (`{"filters": {"docid": "DOC-1"}}`)
- REST and CLI entry points
- Health/metrics endpoints + Prometheus exporter
- Pluggable embeddings and stores; default backend is local

## Requirements
- Python 3.10–3.14

## Install (PyPI)
```bash
python -m venv .venv
source .venv/bin/activate
pip install patchvec
```

CPU-only deployments can use the PyTorch CPU wheel index:
```bash
pip install "patchvec[cpu]" \
  --index-url https://download.pytorch.org/whl/cpu \
  --extra-index-url https://pypi.org/simple
```

## Quickstart
```bash
# Start the server (installed entry point)
pavesrv

# Or run with uvicorn manually if you prefer:
uvicorn pave.main:app --host 0.0.0.0 --port 8086
```

Auth defaults to `none` only for dev. For production, set static auth:
```bash
export PATCHVEC_AUTH__MODE=static
export PATCHVEC_AUTH__GLOBAL_KEY="your-secret"
```

## Minimal config (optional)
By default PatchVec runs with sensible local defaults. To customize, create `config.yml`:
```yaml
vector_store:
  type: default
embedder:
  type: default
auth:
  mode: static
  global_key: ${PATCHVEC_GLOBAL_KEY}
```
Then export:
```bash
export PATCHVEC_CONFIG=./config.yml
export PATCHVEC_GLOBAL_KEY="your-secret"
```

## CLI example
```bash
pavecli create-collection demo books
pavecli upload demo books demo/20k_leagues.txt --docid=verne-20k --metadata='{"lang":"en"}'
pavecli search demo books "captain nemo" -k 5
```

## REST example
```bash
# Create a collection
curl -X POST http://localhost:8086/collections/demo/books \
  -H "Authorization: Bearer your-secret"

# Upload a TXT document
curl -X POST http://localhost:8086/collections/demo/books/documents \
  -H "Authorization: Bearer your-secret" \
  -F "file=@demo/20k_leagues.txt" -F "docid=verne-20k" \
  -F 'metadata={"lang":"en"}'

# Search (GET, no filters)
curl -G --data-urlencode "q=hello" \
  -H "Authorization: Bearer your-secret" \
  http://localhost:8086/collections/demo/books/search

# Search (POST, with filters)
curl -X POST http://localhost:8086/collections/demo/books/search \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"q":"captain nemo","k":5,"filters":{"docid":"verne-20k"}}'
```

## License
GPL-3.0-or-later — (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
