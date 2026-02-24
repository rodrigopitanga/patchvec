<!-- (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net> --> 
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# 🍰 PatchVec — Lightweight, Pluggable Vector Search Microservice

Patchvec is a compact vector store built for people who want provenance and fast
iteration on RAG plumbing. No black boxes, no hidden pipelines: every chunk records
document id, page, and byte offsets, and you can swap embeddings or storage backends per
collection.

## ⚙️ Core capabilities

- **Docker images** — prebuilt CPU/GPU images published to the GitLab Container
  Registry.
- **Tenants and collections** — isolation by tenant with per-collection configuration.
- **Pluggable embeddings** — choose the embedding adapter per collection; wire in local
  or hosted models.
- **REST and CLI** — production use over HTTP, quick experiments with the bundled CLI.
- **Deterministic provenance** — every hit returns doc id, page, offset, and snippet for
  traceability.

## 🧭 Workflows

### 🐳 Docker workflow (prebuilt images)

Pull the image that fits your hardware from the [https://gitlab.com/flowlexi](Flowlexi)
Container Registry on Gitlab (CUDA builds publish as `latest-gpu`, CPU-only as `latest-
cpu`).

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
mkdir -p ~/pv && cd ~/pv #or wherever
python -m venv .venv-pv
source .venv-pv/bin/activate
python -m pip install --upgrade pip
pip install "patchvec[cpu]"

# grab the default configs
curl -LO https://raw.githubusercontent.com/patchvec/patchvec/main/config.yml.example
curl -LO https://raw.githubusercontent.com/patchvec/patchvec/main/tenants.yml.example
cp config.yml.example config.yml
cp tenants.yml.example tenants.yml

# sample demo corpus
curl -LO https://raw.githubusercontent.com/patchvec/patchvec/main/demo/20k_leagues.txt

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

There is a simple Swagger UI available at the root of the server. Just point your
browser to `http://localhost:8086/`

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
pavecli ingest demo books demo/20k_leagues.txt --docid=verne-20k
cp demo/20k_leagues.txt demo/20k_leagues_mod.txt
echo "THE END" >> demo/20k_leagues_mod.txt
pavecli ingest demo books 20k_leagues.txt --docid=verne-20k
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

Building from source relies on the `Makefile` shortcuts (`make install-dev`, `USE_CPU=1
make serve`, `make test`, etc.). The full contributor workflow, target reference, and
task claiming rules live in [CONTRIBUTING.md](CONTRIBUTING.md). Performance benchmarks
are documented in [README-benchmarks.md](README-benchmarks.md).

## 🗺️ Roadmap

Short & mid-term chores are tracked in [`ROADMAP.md`](ROADMAP.md). Pick one, open an
issue titled `claim: <task ID>`, and ship a patch.

## 📜 License

GPL-3.0-or-later — (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
