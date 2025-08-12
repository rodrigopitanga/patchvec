# 👾 Contributing to PatchVec

We welcome PRs, issues, and feedback!

---

## 🛠 Dev Setup
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-test.txt   # includes runtime + test deps
```

## 🧪 Testing
```bash
pytest -q
```
CI/CD blocks releases if tests fail.

## ▶️ Dev Server
```bash
# CPU-only deps by default
make serve
# or explicitly
HOST=0.0.0.0 PORT=8080 RELOAD=1 WORKERS=1 LOG_LEVEL=info ./pavesrv.sh
```

## 🧰 Makefile Targets
- `make install` — install runtime deps (CPU default; `USE_GPU=1` for GPU)
- `make install-dev` — runtime + test deps
- `make serve` — start FastAPI app (uvicorn) with autoreload
- `make test` — run tests
- `make build` — build sdist/wheel (includes ABOUT.md)
- `make package` — create .zip and .tar.gz in ./artifacts
- `make release VERSION=x.y.z` — update versions (setup.py, main.py, Dockerfile, compose, README tags), prepend CHANGELOG with sorted commits since last tag, run tests/build (must pass), tag & push
- `make clean` / `make clean-dist` — cleanup

## 🚢 Release Notes
- Version bumps also update Docker-related version strings where applicable.
- The release target **will not push** if tests/build fail.
- Ensure `PYPI_API_TOKEN` is set in CI to publish on tag.

## 🔐 Secrets & Config
- Don’t commit secrets. Use `.env` (ignored) or env vars in CI.
- For per-tenant keys, use an untracked `tenants.yml` and reference it from `config.yml` (`auth.tenants_file`).
- Config precedence: code defaults < `config.yml` < `tenants.yml` < `PATCHVEC__*` env.

## 📝 Commit Style
Keep commit messages short and scoped:
```
search: fix filter parsing
docs: add curl examples
build: include ABOUT.md in sdist
arch: refactored StoreFactory
```

## 🧩 Architecture (brief)
- Stores: `pave/stores/*` (default txtai/FAISS, qdrant stub)
- Embedders: `pave/embedders/*` (default/txtai, sbert, openai)
- Pure-ish orchestration: `pave/service.py`
- Dependency injection: `build_app()` wires store via `app.state`
