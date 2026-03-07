<!-- (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com> --> 
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# 🍰 PatchVec — Vector Search You Can Understand

PatchVec is a single-process vector search engine that ingests your
documents, chunks and embeds them, and gives you semantic search with
full provenance — document id, page, byte offset, and the exact
snippet that matched. No cluster, no managed service, no
opaque pipelines.

Drop a file in, search it, see exactly what came back and why.

## ⚙️ Why PatchVec

- **Ingest files, not embeddings** — hand it a PDF, CSV, or TXT and
  PatchVec chunks, embeds, and indexes it. No preprocessing pipeline
  to build.
- **Full provenance on every hit** — every search result traces back
  to a document, page, and byte offset. Latency and request
  traceability are built into every response.
- **Multi-tenant by default** — tenant/collection namespacing is
  built in, not bolted on.
- **REST, CLI, or embed it** — run as an HTTP service, script via
  the CLI, or import the library directly in your Python app.
- **Pluggable embeddings** — swap models per collection; wire in
  local or hosted embedding backends.

## 🧭 Workflows

### 🐳 Docker workflow (prebuilt images)

Pull the image that fits your hardware from the
[Flowlexi Container Registry](https://gitlab.com/flowlexi/patchvec/container_registry)
on GitLab (CUDA builds publish as `latest-gpu`, CPU-only as
`latest-cpu`).

```bash
docker pull registry.gitlab.com/flowlexi/patchvec/patchvec:latest-gpu
docker pull registry.gitlab.com/flowlexi/patchvec/patchvec:latest-cpu
```

Run the service by choosing the tag you need and mapping the API port locally:

```bash
docker run -d --name patchvec \
  -p 8086:8086 \
  registry.gitlab.com/flowlexi/patchvec/patchvec:latest-cpu
```

Use the bundled CLI inside the container to create a tenant/collection, ingest a demo
document, and query it:

```bash
docker exec patchvec pavecli create-collection demo books
docker exec patchvec pavecli ingest demo books /app/demo/20k_leagues.txt \
  --docid=verne-20k --metadata='{"lang":"en"}'
docker exec patchvec pavecli search demo books "captain nemo" -k 3
```

See below for REST and UI.

Stop the container when you are done:

```bash
docker rm -f patchvec
```

### 🐍 PyPI workflow

Install Patchvec from PyPI inside an isolated virtual environment and point it at a
local configuration directory.

**Requires Python 3.10–3.14.**

```bash
mkdir -p ~/pv && cd ~/pv  # or wherever
python -m venv .venv-pv
source .venv-pv/bin/activate
python -m pip install --upgrade pip
pip install "patchvec[cpu]"

# grab the default configs
curl -LO https://raw.githubusercontent.com/rodrigopitanga/patchvec/main/config.yml.example
curl -LO https://raw.githubusercontent.com/rodrigopitanga/patchvec/main/tenants.yml.example
cp config.yml.example config.yml
cp tenants.yml.example tenants.yml

# sample demo corpus
curl -LO https://raw.githubusercontent.com/rodrigopitanga/patchvec/main/demo/20k_leagues.txt

# point Patchvec at the config directory and set a local admin key
export PATCHVEC_CONFIG="$HOME/pv/config.yml"
export PATCHVEC_GLOBAL_KEY=super-sekret

# option A: run the service (stays up until you stop it)
pavesrv

# option B: operate entirely via the CLI (no server needed)
pavecli create-collection demo books
pavecli ingest demo books 20k_leagues.txt --docid=verne-20k --metadata='{"lang":"en"}'
pavecli search demo books "captain nemo" -k 3
```

> **CPU-only deployments:** The command above pulls the default PyTorch wheel
> from PyPI, which includes CUDA support (~2 GB). For a leaner, CPU-only torch
> install, point pip at the PyTorch CPU index:
> ```bash
> pip install "patchvec[cpu]" \
> --index-url https://download.pytorch.org/whl/cpu \
> --extra-index-url https://pypi.org/simple
> ```

Deactivate the virtual environment with `deactivate` when finished.

### 🌐 REST API and Web UI usage

When the server is running (either via Docker or `pavesrv`), the API listens on
`http://localhost:8086`. The following `curl` commands mirror the CLI sequence
above—adjust the file path to wherever you stored the corpus
(`/app/demo/20k_leagues.txt` in Docker, `~/pv/20k_leagues.txt` for PyPI installs) and
reuse the bearer token exported earlier:

```bash
# create collection
curl -H "Authorization: Bearer $PATCHVEC_GLOBAL_KEY" \
  -X POST http://localhost:8086/collections/demo/books

# ingest document
curl -H "Authorization: Bearer $PATCHVEC_GLOBAL_KEY" \
  -X POST http://localhost:8086/collections/demo/books/documents \
  -F "file=@20k_leagues.txt" \
  -F 'metadata={"lang":"en"}'

# run search
curl -H "Authorization: Bearer $PATCHVEC_GLOBAL_KEY" \
  "http://localhost:8086/collections/demo/books/search?q=captain+nemo&k=3"
```

Every hit comes back with provenance you can trace, plus latency
and request id for observability:

```json
{
  "matches": [
    {
      "id": "verne-20k::chunk_42",
      "score": 0.82,
      "text": "Captain Nemo conducted me to the central staircase ...",
      "tenant": "demo",
      "collection": "books",
      "match_reason": "semantic",
      "meta": {
        "docid": "verne-20k",
        "filename": "20k_leagues.txt",
        "offset": 8192,
        "lang": "en",
        "ingested_at": "2026-03-07T12:00:00Z"
      }
    }
  ],
  "latency_ms": 12.4,
  "request_id": "req-5f3a-b812"
}
```

The Swagger UI is available at `http://localhost:8086/`.

Health and metrics endpoints are available at `/health` and `/metrics`.

Configuration files copied in either workflow can be customised. Runtime options are
also accepted via the `PATCHVEC_*` environment variable scheme (`PATCHVEC_SERVER__PORT`,
`PATCHVEC_AUTH__MODE`, etc.), which precedes conf files.

### 🔁 Live data updates

Patchvec supports live data refresh without restarting the server. Re-ingest the same
`docid` to *replace* vector content (filename doesn't matter - metadata will change
though), or explicitly delete the document and then ingest it again.

CLI (re-ingest to replace):

```bash
# initial ingest
pavecli ingest demo books 20k_leagues.txt --docid=verne-20k

# modify the content (filename can change — docid is what matters)
cp 20k_leagues.txt 20k_leagues_v2.txt
echo "THE END" >> 20k_leagues_v2.txt

# re-ingest with the same docid to replace the indexed content
pavecli ingest demo books 20k_leagues_v2.txt --docid=verne-20k
```

REST (delete then ingest):

```bash
curl -H "Authorization: Bearer $PATCHVEC_GLOBAL_KEY" \
  -X DELETE http://localhost:8086/collections/demo/books/documents/verne-20k

# make changes

curl -H "Authorization: Bearer $PATCHVEC_GLOBAL_KEY" \
  -X POST http://localhost:8086/collections/demo/books/documents \
  -F "file=@demo/20k_leagues.txt" \
  -F 'docid=verne-20k'
```

### 🛠️ Developer workflow

Building from source relies on `Makefile` shortcuts (`make install-dev`,
`USE_CPU=1 make serve`, `make test`, `make check`, etc.).
The full contributor workflow, target reference, and task claiming rules live in
[CONTRIBUTING.md](CONTRIBUTING.md). Performance benchmarks are documented in
[README-benchmarks.md](README-benchmarks.md).

## Logging

PatchVec writes human-readable logs to stderr and optionally emits
structured JSON lines (one per search/ingest/delete) for production
observability. Enable the ops stream in `config.yml`:

```yaml
log:
  ops_log: stdout   # null (off) | stdout | /path/to/ops.jsonl
```

See `config.yml.example` for the full logging configuration.

## 🗺️ Roadmap

Short & mid-term chores are tracked in [`ROADMAP.md`](ROADMAP.md). Pick one, open an
issue titled `claim: <task ID>`, and ship a patch.

## 📜 License

AGPL-3.0-or-later — (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
