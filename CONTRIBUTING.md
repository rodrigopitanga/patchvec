<!-- (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net> -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# 👾 Contributing to PatchVec

Patchvec accepts code and docs from people who ship patches. Follow the steps below and keep PRs focused.

## Environment setup

```bash
# clone and enter the repo first
git clone https://github.com/patchvec/patchvec.git
cd patchvec

# GPU deps by default; add USE_CPU=1 if you do not have a GPU
make install-dev

# copy local config overrides if you need to tweak behaviour
cp config.yml.example config.yml
cp tenants.yml.example tenants.yml

# optional: run the service right away
USE_CPU=1 make serve
```

Run the test suite before pushing (`USE_CPU=1` if you installed CPU wheels):

```bash
# USE_CPU=1 if you installed CPU deps
make test
```

Need to inspect behaviour without reloads? After tweaking `config.yml` / `tenants.yml`, run `AUTH_MODE=static PATCHVEC_AUTH__GLOBAL_KEY=<your-secret> DEV=0 make serve` for an almost production-like stack, or call the wrapper script directly: `PATCHVEC_AUTH__GLOBAL_KEY=<your-secret> ./pavesrv.sh`.

## Workflow

1. Fork and clone the repository.
2. Create a branch named after the task (`feature/tenant-search`, `fix/csv-metadata`, etc.).
3. Make the change, keep commits scoped, and include tests when possible.
4. Run `make test` and `make check` if you touched deployment or packaging paths.
5. Open a pull request referencing the issue you claimed.

Use imperative, lowercase commit messages (`docs: clarify docker quickstart`).

## Issues and task claims

- `ROADMAP.md` lists chores that need owners.
- To claim a task, open an issue titled `claim: <task>` and describe the approach.
- Good first issues live under the `good-first-issue` label. Submit a draft PR within a few days of claiming.

## Code style

- Prefer direct, readable Python. Keep imports sorted and avoid wildcard imports.
- Follow PEP 8 defaults, keep line length ≤ 88 characters, and run `ruff` locally if you have it installed.
- Do not add framework abstractions unless they solve a concrete problem.
- Avoid adding dependencies without discussing them in an issue first.

## Pull request checklist

- [ ] Tests pass locally (`make test`, add `USE_CPU=1` if you installed CPU wheels).
- [ ] Packaged stack still works (`make check` on a clean checkout).
- [ ] Docs updated when behavior changes.
- [ ] PR description states what changed and why.

Ship code, not questions. If you need help, post logs and the failing command instead of asking for permission.

## Architecture

- Stores live under `pave/stores/*` (default txtai/FAISS today, Qdrant stub ready).
- Embedding adapters reside in `pave/embedders/*` (txtai, sentence-transformers, OpenAI, etc.).
- `pave/service.py` wires the FastAPI application and injects the store into `app.state`.
- CLI entrypoints are defined in `pave/cli.py`; shell shims `pavecli.sh`/`pavesrv.sh` wrap the same commands for repo contributors.

## 🧰 Makefile Targets

- `make install` — install runtime deps (CPU wheels by default; `USE_GPU=1` for GPU builds).
- `make install-dev` — runtime + test deps for contributors.
- `make serve` — start the FastAPI app (uvicorn) with autoreload (`USE_CPU=1` for CPU-only setups).
- `make test` — run the pytest suite.
- `make check` — build and smoke-test the container image with the demo corpus.
- `make build` — build sdist/wheel (includes ABOUT.md).
- `make package` — create `.zip`/`.tar.gz` artifacts under `./artifacts`.
- `make release VERSION=x.y.z` — sync version strings, regenerate the changelog, run tests/build, tag & push.
- `make clean` / `make clean-dist` — remove caches and build outputs.
