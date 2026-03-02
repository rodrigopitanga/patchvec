# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import asyncio, functools, json, os, logging, shutil, time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import uvicorn

from fastapi import FastAPI, Header, Body, File, UploadFile, Form, Path, \
    Query, Depends, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse
from fastapi.concurrency import run_in_threadpool
from typing import Any
from starlette.background import BackgroundTask

from pave.config import get_cfg, get_logger
from pave.auth import AuthContext, auth_ctx, tenant_rate_limit, \
    enforce_policy, resolve_bind
from pave.metrics import inc, set_error, snapshot, to_prometheus, \
    reset as metrics_reset, set_data_dir as metrics_set_data_dir, \
    flush as metrics_flush
from pave.stores.factory import get_store
from pave.stores.base import BaseStore
from pave.service import \
    create_collection as svc_create_collection, \
    dump_archive as svc_dump_archive, \
    restore_archive as svc_restore_archive, \
    delete_collection as svc_delete_collection, \
    rename_collection as svc_rename_collection, \
    delete_document as svc_delete_document, \
    ingest_document as svc_ingest_document, \
    list_tenants as svc_list_tenants, \
    list_collections as svc_list_collections, \
    search as svc_search, ServiceError
from pave.schemas import SearchBody, RenameCollectionBody, SearchResponse, \
    ErrorResponse
from pave.ui import attach_ui
import pave.log as ops_log
from pave.log import ops_event

VERSION = "0.5.8a1"


def _hw_info() -> dict:
    """Collect server hardware info once at startup (stdlib-only, multiplatform)."""
    import platform, sys
    info: dict = {
        "hw_cpu":   platform.processor() or platform.machine(),
        "hw_cores": os.cpu_count(),
        "hw_os":    f"{platform.system()} {platform.release()}",
    }
    try:
        if sys.platform == "linux":
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        info["hw_ram_gb"] = round(int(line.split()[1]) / 1_000_000, 1)
                        break
        elif sys.platform == "darwin":
            import subprocess
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True, timeout=2
            )
            info["hw_ram_gb"] = round(int(out.strip()) / 1_000_000_000, 1)
    except Exception:
        pass
    return info


# Dependency injection builder
def build_app(cfg=get_cfg()) -> FastAPI:

    log = get_logger()

    def _resp(*codes: int) -> dict[int, dict[str, type[ErrorResponse]]]:
        return {code: {"model": ErrorResponse} for code in codes}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Eagerly load the sentence-transformer model so the first
        # request doesn't pay the cold-start penalty.
        try:
            app.state.store.load_or_init("_system", "health")
            log.info("Embedding model warm-up complete")
        except Exception as e:
            log.warning(f"Embedding model warm-up failed: {e}")
        yield
        metrics_flush()
        ops_log.close()
        for _exec in (app.state.search_executor, app.state.ingest_executor):
            if _exec is not None:
                _exec.shutdown(wait=False)

    app = FastAPI(
        title=cfg.get("instance.name","Patchvec"),
        description=cfg.get("instance.desc","Vector Search Microservice"),
        lifespan=lifespan,
    )
    app.state.store = get_store(cfg)
    app.state.cfg = cfg
    app.state.version = VERSION
    app.state.hw_info = _hw_info()

    # Search limits
    _max_conc = int(cfg.get("search.max_concurrent"))
    _to_ms = int(cfg.get("search.timeout_ms"))
    # Dedicated executor: threads == max_concurrent so work starts immediately.
    app.state.search_executor = (
        ThreadPoolExecutor(max_workers=_max_conc) if _max_conc > 0 else None
    )
    # Plain counter instead of threading.Semaphore: check+increment has no
    # await between them, so it is atomic in the asyncio event loop.
    app.state.max_searches = _max_conc
    app.state.active_searches = 0
    app.state.search_timeout_s = _to_ms / 1000.0 if _to_ms > 0 else 0.0

    _max_iconc = int(cfg.get("ingest.max_concurrent"))
    app.state.ingest_executor = (
        ThreadPoolExecutor(max_workers=_max_iconc) if _max_iconc > 0 else None
    )
    app.state.max_ingests = _max_iconc
    app.state.active_ingests = 0

    # Per-tenant concurrency limits
    _tenants_cfg = cfg.get("tenants") or {}
    _raw_def = (
        _tenants_cfg.get("default_max_concurrent")
        if isinstance(_tenants_cfg, dict) else None
    )
    app.state.tenant_default_limit = int(_raw_def) if _raw_def is not None else 0
    app.state.tenant_limits = {}
    app.state.tenant_active = {}
    for _t, _tcfg in (_tenants_cfg.items() if isinstance(_tenants_cfg, dict) else []):
        if _t == "default_max_concurrent" or not isinstance(_tcfg, dict):
            continue
        _lim = _tcfg.get("max_concurrent")
        if _lim is not None:
            app.state.tenant_limits[_t] = int(_lim)
            app.state.tenant_active[_t] = 0

    ops_log.configure(cfg.get("log.ops_log"))

    async def _do_search(fn):
        """Concurrency gate + timeout wrapper for all search handlers."""
        timeout_s = app.state.search_timeout_s
        max_s = app.state.max_searches
        # Check-and-increment has no await between them: atomic in asyncio.
        if max_s > 0:
            if app.state.active_searches >= max_s:
                return _error(
                    503, "search_overloaded",
                    "too many concurrent searches, try again later",
                )
            app.state.active_searches += 1
        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(app.state.search_executor, fn)
            try:
                if timeout_s > 0:
                    result = await asyncio.wait_for(
                        asyncio.shield(future), timeout=timeout_s
                    )
                else:
                    result = await future
                return JSONResponse(result)
            except asyncio.TimeoutError:
                # Thread keeps running; suppress its eventual result/exception.
                future.add_done_callback(
                    lambda f: f.exception() if not f.cancelled() else None
                )
                return _error(
                    503, "search_timeout",
                    f"search timed out after {int(timeout_s * 1000)}ms",
                )
            except ServiceError as exc:
                return _error(500, exc.code, exc.message)
        finally:
            if max_s > 0:
                app.state.active_searches -= 1

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code", "http_error")
            message = detail.get("error") or detail.get("message") or str(detail)
        else:
            code = "http_error"
            message = str(detail)
        return JSONResponse(
            {"ok": False, "code": code, "error": message},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    # Initialize metrics persistence
    data_dir = cfg.get("data_dir")
    if data_dir:
        metrics_set_data_dir(data_dir)

    def current_store(request: Request) -> BaseStore:
        return request.app.state.store


    # -------------------- Health --------------------

    def _readiness_check() -> dict[str, Any]:
        details: dict[str, Any] = {
            "data_dir": cfg.get("data_dir"),
            "vector_store": cfg.get("vector_store.type"),
            "writable": False,
            "vector_backend_init": False,
        }
        try:
            os.makedirs(cfg.data_dir, exist_ok=True)
            testfile = os.path.join(cfg.data_dir, ".writetest")
            with open(testfile, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(testfile)
            details["writable"] = True
        except Exception as e:
            details["writable"] = False
            set_error(f"fs: {e}")
        try:
            request_store = app.state.store
            request_store.load_or_init("_system", "health")
            details["vector_backend_init"] = True
        except Exception as e:
            details["vector_backend_init"] = False
            set_error(f"vec: {e}")
        details["ok"] = bool(
            details["writable"] and details["vector_backend_init"])
        details["version"] = VERSION
        return details

    @app.get("/health")
    def health():
        inc("requests_total")
        d = _readiness_check()
        status = "ready" if d.get("ok") else "degraded"
        return {"ok": d["ok"], "status": status, "version": VERSION}

    @app.get("/health/live")
    def health_live():
        inc("requests_total")
        return {"ok": True, "status": "live", "version": VERSION}

    @app.get("/health/ready")
    def health_ready():
        inc("requests_total")
        d = _readiness_check()
        code = 200 if d.get("ok") else 503
        return JSONResponse(d, status_code=code)

    @app.get("/health/metrics")
    def health_metrics():
        inc("requests_total")
        extra = {
            "version": VERSION,
            "vector_store": cfg.get("vector_store.type"),
            "auth": cfg.get("auth.mode"),
            **app.state.hw_info,
        }
        return snapshot(extra)

    @app.get("/metrics")
    def metrics_prom():
        inc("requests_total")
        txt = to_prometheus(build={
            "version": VERSION,
            "vector_store": cfg.get("vector_store.type"),
            "auth":cfg.get("auth.mode")
        })
        return PlainTextResponse(txt, media_type="text/plain; version=0.0.4")


    # ----------------- Core API ------------------

    def _error(status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            {"ok": False, "code": code, "error": message},
            status_code=status_code,
        )

    @app.get(
        "/admin/archive",
        response_class=FileResponse,
        responses=_resp(401, 403, 404, 500),
    )
    async def dump_archive(
        ctx: AuthContext = Depends(auth_ctx),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        if not ctx.is_admin:
            return _error(403, "admin_required", "admin access required")

        data_dir = cfg.get("data_dir")
        if not data_dir:
            return _error(
                500,
                "data_dir_not_configured",
                "data directory is not configured",
            )

        try:
            archive_path, tmp_dir = await run_in_threadpool(
                svc_dump_archive, store, data_dir
            )
        except FileNotFoundError:
            return _error(404, "data_dir_not_found", "data directory not found")
        except Exception as exc:
            return _error(
                500,
                "archive_dump_failed",
                f"failed to dump archive: {exc}",
            )

        filename = os.path.basename(archive_path)

        def _cleanup(path: str | None) -> None:
            if not path:
                return
            shutil.rmtree(path, ignore_errors=True)

        background = BackgroundTask(_cleanup, tmp_dir)
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=filename,
            background=background,
        )

    @app.put(
        "/admin/archive",
        responses=_resp(400, 401, 403, 500),
    )
    async def restore_archive(
        ctx: AuthContext = Depends(auth_ctx),
        store: BaseStore = Depends(current_store),
        file: UploadFile = File(...),
    ):
        inc("requests_total")
        if not ctx.is_admin:
            return _error(403, "admin_required", "admin access required")

        data_dir = cfg.get("data_dir")
        if not data_dir:
            return _error(
                500,
                "data_dir_not_configured",
                "data directory is not configured",
            )

        content = await file.read()
        try:
            out = await run_in_threadpool(
                svc_restore_archive, store, data_dir, content
            )
            return out
        except ValueError as exc:
            return _error(400, "archive_invalid", str(exc))
        except Exception as exc:
            return _error(
                500,
                "archive_restore_failed",
                f"failed to restore archive: {exc}",
            )

    @app.delete(
        "/admin/metrics",
        responses=_resp(401, 403),
    )
    def delete_metrics(
        ctx: AuthContext = Depends(auth_ctx),
    ):
        inc("requests_total")
        if not ctx.is_admin:
            return _error(403, "admin_required", "admin access required")
        return metrics_reset()

    @app.get(
        "/admin/tenants",
        responses=_resp(401, 403, 500),
    )
    def list_tenants(
        ctx: AuthContext = Depends(auth_ctx),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        if not ctx.is_admin:
            return _error(403, "admin_required", "admin access required")
        data_dir = cfg.get("data_dir")
        if not data_dir:
            return _error(
                500,
                "data_dir_not_configured",
                "data directory is not configured",
            )
        result = svc_list_tenants(store, data_dir)
        if not result.get("ok"):
            return _error(
                500,
                result.get("code", "list_tenants_failed"),
                result.get("error", "failed to list tenants"),
            )
        return result

    @app.get(
        "/collections/{tenant}",
        responses=_resp(401, 403, 429, 500),
    )
    @ops_event("list_collections", coll=None)
    def list_collections(
        tenant: str,
        ctx: AuthContext = Depends(tenant_rate_limit),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        result = svc_list_collections(store, tenant)
        if not result.get("ok"):
            return _error(
                500,
                result.get("code", "list_collections_failed"),
                result.get("error", "failed to list collections"),
            )
        return result

    @app.post(
        "/collections/{tenant}/{name}",
        status_code=201,
        responses=_resp(401, 403, 429, 500),
    )
    @ops_event("create_collection")
    def create_collection(
        tenant: str,
        name: str,
        ctx: AuthContext = Depends(tenant_rate_limit),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        result = svc_create_collection(store, tenant, name)
        if not result.get("ok"):
            return _error(
                500,
                result.get("code", "create_collection_failed"),
                result.get("error", "failed to create collection"),
            )
        return result

    @app.delete(
        "/collections/{tenant}/{name}",
        responses=_resp(401, 403, 429, 500),
    )
    @ops_event("delete_collection")
    def delete_collection(
        tenant: str,
        name: str,
        ctx: AuthContext = Depends(tenant_rate_limit),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        result = svc_delete_collection(store, tenant, name)
        if not result.get("ok"):
            return _error(
                500,
                result.get("code", "delete_collection_failed"),
                result.get("error", "failed to delete collection"),
            )
        return result

    @app.put(
        "/collections/{tenant}/{name}",
        responses=_resp(400, 401, 403, 404, 409, 429, 500),
    )
    @ops_event(
        "rename_collection",
        new_name=lambda kw, r: kw["body"].new_name,
    )
    def rename_collection(
        tenant: str,
        name: str,
        body: RenameCollectionBody,
        ctx: AuthContext = Depends(tenant_rate_limit),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        result = svc_rename_collection(store, tenant, name, body.new_name)
        if not result.get("ok"):
            error_type = result.get("error_type", "invalid")
            status_map = {
                "not_found": 404,
                "conflict": 409,
                "invalid": 400,
                "failed": 500,
            }
            status_code = status_map.get(error_type, 500)
            return _error(
                status_code,
                result.get("code", "rename_invalid"),
                result.get("error", "failed to rename collection"),
            )
        return result

    @app.post(
        "/collections/{tenant}/{collection}/documents",
        status_code=201,
        responses=_resp(400, 401, 403, 413, 429, 500, 503),
    )
    @ops_event(
        "ingest", coll="collection",
        docid=lambda kw, r: (
            kw.get("docid") or getattr(kw.get("file"), "filename", None)
        ),
        chunks=lambda kw, r: (
            r.get("chunks") if isinstance(r, dict) and r.get("ok") else None
        ),
    )
    async def ingest_document(
        tenant: str,
        collection: str,
        file: UploadFile = File(...),
        docid: str | None = Form(None),
        metadata: str | None = Form(None),
        # CSV controls as optional query params
        # (kept out of form to not clash with file upload)
        csv_has_header: str | None = Query(None, pattern="^(auto|yes|no)$"),
        csv_meta_cols: str | None = Query(None),
        csv_include_cols: str | None = Query(None),
        ctx: AuthContext = Depends(tenant_rate_limit),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        meta_obj = None
        if metadata:
            try:
                meta_obj = json.loads(metadata)
            except Exception as e:
                return _error(
                    400,
                    "invalid_metadata_json",
                    f"invalid metadata json: {e}",
                )

        content = await file.read()

        max_mb = float(cfg.get("ingest.max_file_size_mb"))
        max_bytes = int(max_mb * 1024 * 1024)
        if max_bytes > 0 and len(content) > max_bytes:
            return _error(
                413,
                "file_too_large",
                f"file exceeds the {int(max_mb)} MB limit",
            )

        csv_opts = None
        if csv_has_header or csv_meta_cols or csv_include_cols:
            csv_opts = {
                "has_header": csv_has_header or "auto",
                "meta_cols": csv_meta_cols or "",
                "include_cols": csv_include_cols or "",
            }

        max_i = app.state.max_ingests
        if max_i > 0:
            if app.state.active_ingests >= max_i:
                return _error(
                    503, "ingest_overloaded",
                    "too many concurrent ingests, try again later",
                )
            app.state.active_ingests += 1
        try:
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    app.state.ingest_executor,
                    functools.partial(
                        svc_ingest_document,
                        store, tenant, collection, file.filename, content,
                        docid, meta_obj, csv_options=csv_opts,
                    ),
                )
                if not result.get("ok"):
                    code = result.get("code", "ingest_failed")
                    status_map = {
                        "no_text_extracted": 400,
                        "ingest_failed": 500,
                    }
                    return _error(
                        status_map.get(code, 500),
                        code,
                        result.get("error", "failed to ingest document"),
                    )
                return result
            except ServiceError as exc:
                code = exc.code
                status_map = {
                    "invalid_csv_options": 400,
                    "ingest_failed": 500,
                }
                return _error(
                    status_map.get(code, 500),
                    code,
                    exc.message,
                )
        finally:
            if max_i > 0:
                app.state.active_ingests -= 1

    @app.delete(
        "/collections/{tenant}/{collection}/documents/{docid}",
        responses=_resp(401, 403, 429, 500),
    )
    @ops_event("delete_doc", coll="collection", docid="docid")
    def delete_document(
        tenant: str,
        collection: str,
        docid: str,
        ctx: AuthContext = Depends(tenant_rate_limit),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        result = svc_delete_document(store, tenant, collection, docid)
        if not result.get("ok"):
            return _error(
                500,
                result.get("code", "delete_document_failed"),
                result.get("error", "failed to delete document"),
            )
        return result

    # POST search (supports filters)
    @app.post(
        "/collections/{tenant}/{name}/search",
        response_model=SearchResponse,
        responses=_resp(401, 403, 429, 500, 503),
    )
    @ops_event(
        "search", coll="name",
        k=lambda kw, r: kw["body"].k,
        hits=lambda kw, r: (
            len(json.loads(r.body).get("matches", []))
            if getattr(r, "status_code", 400) < 400 else None
        ),
        request_id=lambda kw, r: (
            kw["body"].request_id or kw.get("x_request_id")
        ),
    )
    async def search_post(
        tenant: str,
        name: str,
        body: SearchBody,
        x_request_id: str | None = Header(None, alias="X-Request-ID"),
        ctx: AuthContext = Depends(tenant_rate_limit),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        request_id = body.request_id or x_request_id
        include_common = bool(cfg.common_enabled)
        return await _do_search(functools.partial(
            svc_search,
            store, tenant, name, body.q, body.k,
            filters=body.filters,
            include_common=include_common,
            common_tenant=cfg.common_tenant,
            common_collection=cfg.common_collection,
            request_id=request_id,
        ))

    # GET search (no filters)
    @app.get(
        "/collections/{tenant}/{name}/search",
        responses=_resp(401, 403, 429, 500, 503),
    )
    @ops_event(
        "search", coll="name",
        k="k",
        hits=lambda kw, r: (
            len(json.loads(r.body).get("matches", []))
            if getattr(r, "status_code", 400) < 400 else None
        ),
        request_id="x_request_id",
    )
    async def search_get(
        tenant: str,
        name: str,
        q: str = Query(...),
        k: int = Query(5, ge=1),
        x_request_id: str | None = Header(None, alias="X-Request-ID"),
        ctx: AuthContext = Depends(tenant_rate_limit),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        include_common = bool(cfg.common_enabled)
        return await _do_search(functools.partial(
            svc_search,
            store, tenant, name, q, k,
            filters=None,
            include_common=include_common,
            common_tenant=cfg.common_tenant,
            common_collection=cfg.common_collection,
            request_id=x_request_id,
        ))

    # Common collection search
    @app.post(
        "/search",
        responses=_resp(401, 403, 500, 503),
    )
    async def search_common_post(
        body: SearchBody,
        x_request_id: str | None = Header(None, alias="X-Request-ID"),
        ctx: AuthContext = Depends(auth_ctx),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        request_id = body.request_id or x_request_id
        if not cfg.common_enabled:
            return JSONResponse({
                "matches": [],
                "latency_ms": 0.0,
                "request_id": request_id,
            })
        return await _do_search(functools.partial(
            svc_search,
            store, cfg.common_tenant, cfg.common_collection,
            body.q, body.k,
            filters=body.filters,
            request_id=request_id,
        ))

    @app.get(
        "/search",
        responses=_resp(401, 403, 500, 503),
    )
    async def search_common_get(
        q: str = Query(...),
        k: int = Query(5, ge=1),
        x_request_id: str | None = Header(None, alias="X-Request-ID"),
        ctx: AuthContext = Depends(auth_ctx),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        if not cfg.common_enabled:
            return JSONResponse({
                "matches": [],
                "latency_ms": 0.0,
                "request_id": x_request_id,
            })
        return await _do_search(functools.partial(
            svc_search,
            store, cfg.common_tenant, cfg.common_collection,
            q, k,
            filters=None,
            request_id=x_request_id,
        ))

    return app

def main_srv():
    """
    HTTP server entrypoint.
    Precedence: CFG (reads env first) > defaults.
    """
    cfg = get_cfg()
    log = get_logger()
    # Policy:
    # - fail fast without auth in prod;
    # - auth=none only in dev with loopback;
    # - raises on invalid config.
    enforce_policy(cfg)

    # resolve bind host/port
    host, port = resolve_bind(cfg)
    cfg.set("server.host", host)
    cfg.set("server.port", port)

    # flags from CFG
    reload = bool(cfg.get("server.reload", False))
    workers = int(cfg.get("server.workers", 1))
    log_level = str(cfg.get("log.level")).lower()
    timeout_keep_alive = int(cfg.get("server.timeout_keep_alive"))

    if cfg.get("dev",0):
        log_level = "debug"
        log.setLevel(logging.DEBUG)

    _s_cap = int(cfg.get("search.max_concurrent"))
    _s_to = int(cfg.get("search.timeout_ms"))
    _i_cap = int(cfg.get("ingest.max_concurrent"))
    _tc = cfg.get("tenants") or {}
    _tcap = (
        int(_tc.get("default_max_concurrent") or 0)
        if isinstance(_tc, dict) else 0
    )
    _ops_dest = cfg.get("log.ops_log") or "null"
    _acc_dest = cfg.get("log.access_log")
    log.info(f"┌─ Welcome to PatchVEC 🍰 v{VERSION}")
    log.info(
        f"│  auth={cfg.get('auth.mode','none')} "
        f"store={cfg.get('vector_store.type','default')} "
        f"data_dir={cfg.get('data_dir')} "
        f"bind={host}:{port} workers={workers}"
    )
    log.info(
        f"│  search_cap={_s_cap} search_to={_s_to}ms "
        f"ingest_cap={_i_cap} "
        f"tenant_cap={'unlimited' if _tcap == 0 else _tcap} "
        f"ops_log={_ops_dest}"
    )
    log.info("└" + "─" * 40)

    # Access log routing
    _acc_val = str(_acc_dest).strip().lower() if _acc_dest else ""
    if _acc_val and _acc_val not in ("null", "none"):
        if _acc_val != "stdout":
            logging.getLogger("uvicorn.access").addHandler(
                logging.FileHandler(_acc_dest)
            )
    _access_log = True

    # run server
    uvicorn.run("pave.main:app",
                host=host,
                port=port,
                reload=reload,
                workers=workers,
                log_level=log_level,
                timeout_keep_alive=timeout_keep_alive,
                access_log=_access_log,
                )

# Lazy module-level `app` — only built when first accessed (e.g. by uvicorn).
# Importing `build_app` or `VERSION` from this module is now side-effect-free.
_app = None

def __getattr__(name: str):
    if name == "app":
        global _app
        if _app is None:
            _app = build_app()
            try:
                attach_ui(_app)
            except Exception:
                pass
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

if __name__ == "__main__":
    main_srv()
