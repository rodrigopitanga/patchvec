# 🍰 PatchVec — Lightweight, Pluggable Vector Search Microservice

Upload → chunk → index (with metadata) → search via REST and CLI.

---

## 🚀 Quickstart

### 🖥️ CPU-only Dev (default)
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-cpu.txt
./pavesrv.sh
```

### 📦 Install from PyPI
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install patchvec[cpu]   # or patchvec[gpu] for CUDA
```

### ▶️ Run the Server
From source:
```bash
./pavesrv.sh
```
From PyPI:
```bash
pavesrv
```

### ⚙️ Minimal Config
For production (static auth), set env vars (do not commit secrets):
```env
PATCHVEC_AUTH__MODE=static
PATCHVEC_AUTH__GLOBAL_KEY=sekret-passwod
```
(Optional: copy `config.yml.example` to an untracked `config.yml` and tweak as needed)
(Tip: use an untracked `tenants.yml` and point `auth.tenants_file` to it in `config.yml`.)

---

## 🔧 Overriding Server Settings (uvicorn)
You can override a few server knobs via environment variables:
```bash
HOST=127.0.0.1 PORT=9000 RELOAD=1 WORKERS=4 LOG_LEVEL=debug pavesrv
```
> Note: Full configuration uses the `PATCHVEC_...` env scheme (e.g., `PATCHVEC_SERVER__PORT=9000`).

---

## 🌐 REST API Examples

**Create a collection**
```bash
curl -X POST "http://localhost:8086/collections/acme/invoices"
```

**Upload a TXT/PDF/CSV document**
```bash
curl -X POST "http://localhost:8086/collections/acme/invoices/documents"   -F "file=@sample.txt"   -F "docid=DOC-1"   -F 'metadata={"lang":"pt"}'
```

**Search (GET, no filters)**
```bash
curl "http://localhost:8086/collections/acme/invoices/search?q=garantia&k=5"
```

**Search (POST with filters)**
```bash
curl -X POST "http://localhost:8086/collections/acme/invoices/search"   -H "Content-Type: application/json"   -d '{"q": "garantia", "k": 5, "filters": {"docid": "DOC-1"}}'
```

**Health / Metrics**
```bash
curl "http://localhost:8086/health"
curl "http://localhost:8086/metrics"
```

---

## 📜 License
GPL-3.0-or-later — (C) 2025 Rodrigo Rodrigues da Silva
