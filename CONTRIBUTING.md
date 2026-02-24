<!-- (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net> -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# 👾 Contributing to PatchVec

Patchvec accepts code and docs from people who ship patches. Follow the steps below and
keep PRs focused.

## Environment setup

```bash
# clone and enter the repo first
git clone https://github.com/patchvec/patchvec.git
cd patchvec

# GPU deps by default; add USE_CPU=1 if you want CPU-only torch wheels
make install-dev

# copy local config overrides if you need to tweak behaviour
cp config.yml.example config.yml
cp tenants.yml.example tenants.yml

# optional: run the service right away
USE_CPU=1 make serve
```

Run the test suite before pushing (`USE_CPU=1` if you installed CPU wheels):

```bash
# USE_CPU=1 if you installed CPU-only deps
make test
```

Need to inspect behaviour without reloads? After tweaking `config.yml` / `tenants.yml`,
run `AUTH_MODE=static PATCHVEC_AUTH__GLOBAL_KEY=<your-secret> DEV=0 make serve` for an
almost production-like stack, or call the wrapper script directly:
`PATCHVEC_AUTH__GLOBAL_KEY=<your-secret> ./pavesrv.sh`.

## Workflow

1. Fork and clone the repository (menu above).
2. Create a branch named after the task (`feature/tenant-search`, `fix/csv-metadata`,
   etc.).
3. Make the change, keep commits scoped, and include tests whenever applicable.
4. Run `make test` and `make check` or `make package` if you touched deployment or
   packaging paths.
5. Open a pull request referencing the issue you claimed.

## Code style

- Prefer direct, readable Python. Keep imports sorted and avoid wildcard imports.
- Follow PEP 8 defaults, keep line length ≤ 88 characters, and run `ruff` locally if you
  have it installed.
- Do not add framework abstractions unless they solve a concrete problem.
- Avoid adding dependencies without discussing them in an issue first.
- Use Python 3.10+ syntax (e.g. `dict` instead of `Dict`)

## Commit messages

Use the `[tag]` prefix format for commits that affect functionality:

```
[tag] Short imperative description (≤72 chars)
```

**Style:** One-liners are preferred. For complex commits, skip a line and add a
breakdown:

```
[core] Add collection rename across all layers

- Store: abstract method + TxtaiStore implementation with deadlock-safe locking
- Service: rename_collection() with error handling
- API: PUT /collections/{tenant}/{name} endpoint
- CLI: rename-collection command
```

**Available tags** (mapped to changelog sections):

| Tag | Changelog Section | Use for |
|-----|-------------------|---------|
| `[core]` | Core | Cross-cutting features, service logic layer |
| `[api]` | API | REST endpoints, request/response schemas |
| `[cli]` | CLI | Command-line interface changes |
| `[store]` | Store | Vector store backends, indexing |
| `[conf]` | Configuration | Configuration management |
| `[fix]` | Bug Fixes | Bug fixes |
| `[perf]` | Performance | Optimizations, benchmarks |
| `[build]` | Build | Build system, dependencies (make, pip) |
| `[pkg]` | Packaging | PyPI/Docker packaging |
| `[doc]` | Documentation | README, docstrings, guides |
| `[test]` | Testing | Test suite changes |
| `[ui]` | UI | Web UI changes |
| `[infra]` | Infrastructure | CI/CD, deployment scripts |

**Two tags max**, most relevant first: `[api][cli] Add delete document endpoint`

**Chores** use `chore:` for maintenance that doesn't affect functionality:

```
chore: update copyright headers
chore(deps): bump txtai to 8.x
```

**Changelog:** Only commits starting with `[tag]` or `chore:` are included. Release
commits (`chore(release): vX.Y.Z`) are auto-skipped.

## Issues and task claims

- `ROADMAP.md` lists chores that need owners.
- To claim a task, open an issue titled `claim: <task ID>` and describe the
approach.
- Good first issues live under the `bite-sized` label. Submit a draft PR
within a few days of claiming.

## Pull request checklist

- [ ] Tests pass locally (`make test`, always add `USE_CPU=1`, also run
without it if you have a properly configured GPU).
- [ ] Inform OS and pip freeze.
- [ ] Docs updated when behavior changes.
- [ ] PR description states what changed and why.
- [ ] PR is self-contained.
- [ ] If it closes an issue, mention it; if it closes a [ROADMAP.md] item, strike it
  through.

Ship code, not questions. If you need help, post logs and the failing command instead of
asking for permission to ask.

## API response policy

- Use HTTP status codes for success vs failure (no 200 for errors).
- Errors must use the standard envelope:
  `{"ok": false, "code": "...", "error": "...", "details"?}`.
- Error `code` values are created in the service layer whenever possible.
- Service raises `ServiceError(code, message)` for exceptional failures.
- API/CLI render the error envelope and preserve HTTP status codes.
- Success responses stay unwrapped (simple payloads).
- Cross-cutting metadata (e.g., `request_id`, `latency_ms`) may appear as
  top-level fields on success and error responses.
- Typed error schema: `ErrorResponse` in `pave/schemas.py` documents the
  envelope for OpenAPI and future client SDKs.

## Architecture

- Stores live under `pave/stores/*` (default txtai/FAISS today, Qdrant stub
ready).
- Embedding adapters reside in `pave/embedders/*` (txtai,
sentence-transformers, OpenAI, etc.).
- `pave/service.py` wires the FastAPI application and injects the store into
`app.state`.
- CLI entrypoints are defined in `pave/cli.py`; shell shims `pavecli.sh`/`pavesrv.sh`
  wrap the same commands for repo contributors.

## Makefile Targets (base by default; `USE_CPU=1` for CPU-only wheels).

- `make install` — install runtime deps.
- `make install-dev` — runtime + test deps for contributors.
- `make serve` — start the FastAPI app (uvicorn) with autoreload.
- `make test` — run the pytest suite.
- `make check` — build and smoke-test the container image with the demo corpus.
- `make build` — build sdist/wheel (includes ABOUT.md).
- `make package` — create `.zip`/`.tar.gz` artifacts under `./artifacts`.
- `make changelog` — preview the new changelog entry (no write).
- `make changelog-write` — update `CHANGELOG.md` for `VERSION`.
- `make release VERSION=x.y.z` — bump versions, regenerate changelog, run tests/build,
  create artifacts (`./artifacts`), tag (no push), and build Docker images:
  - If `USE_CPU` is not set, builds both CPU and GPU images.
  - If `USE_CPU=0` or `USE_CPU=1`, builds only the requested variant.
  - If `DOCKER_PUBLISH=1`, pushes images; otherwise builds only.

### If `make release` fails

`make release VERSION=x.y.z` is safe to re-run after fixing the failure:

- **Failed before commit** (e.g. tests): bumped files are uncommitted. Fix and
  re-run, or `git checkout -- .` to start clean.
- **Failed after commit, before tag**: re-run skips the commit (nothing staged)
  and creates the tag normally.
- **Failed after tag** (e.g. Docker): re-run skips the commit, then prompts
  `Re-tag? [y/N]` — answer `N` to keep the existing tag and continue from the
  Docker step.

## Release tags and GitLab CI

Pushing a tag to the GitLab repository triggers the release pipeline
automatically (no manual steps). Tag format:
`vX.Y.Z` where each component is 1–4 digits, with an optional suffix up to 16
non-whitespace characters (e.g. `rc1`, `a0`, `b2`).

| Tag pattern | PyPI | TestPyPI | GitLab Package Registry | Docker |
|-------------|------|----------|-------------------------|--------|
| `vX.Y.Z` | ✓ | — | ✓ | CPU + GPU |
| `vX.Y.ZrcN` (N ≤ 999) | — | ✓ | ✓ | CPU only |
| `vX.Y.Z<other>` | — | — | ✓ | — |
- `make clean` / `make clean-dist` — remove caches and build outputs.
