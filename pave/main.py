# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json, os, logging, shutil
from contextlib import asynccontextmanager
import uvicorn

from fastapi import FastAPI, Header, Body, File, UploadFile, Form, Path, \
    Query, Depends, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse
from fastapi.concurrency import run_in_threadpool
from typing import Any
from starlette.background import BackgroundTask

from pave.config import get_cfg, get_logger
from pave.auth import AuthContext, auth_ctx, authorize_tenant, \
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


VERSION = "0.5.8a0"

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
            log.warning("Embedding model warm-up failed: %s", e)
        yield
        metrics_flush()

    app = FastAPI(
        title=cfg.get("instance.name","Patchvec"),
        description=cfg.get("instance.desc","Vector Search Microservice"),
        lifespan=lifespan,
    )
    app.state.store = get_store(cfg)
    app.state.cfg = cfg
    app.state.version = VERSION

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
            "auth": cfg.get("auth.mode")
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
        responses=_resp(401, 403, 500),
    )
    def list_collections(
        tenant: str,
        ctx: AuthContext = Depends(authorize_tenant),
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
        responses=_resp(401, 403, 500),
    )
    def create_collection(
        tenant: str,
        name: str,
        ctx: AuthContext = Depends(authorize_tenant),
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
        responses=_resp(401, 403, 500),
    )
    def delete_collection(
        tenant: str,
        name: str,
        ctx: AuthContext = Depends(authorize_tenant),
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
        responses=_resp(400, 401, 403, 404, 409, 500),
    )
    def rename_collection(
        tenant: str,
        name: str,
        body: RenameCollectionBody,
        ctx: AuthContext = Depends(authorize_tenant),
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
        responses=_resp(400, 401, 403, 500),
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
        ctx: AuthContext = Depends(authorize_tenant),
        store: BaseStore = Depends(current_store),
    ):
        meta_obj = None
        if metadata:
            try:
                import json
                meta_obj = json.loads(metadata)
            except Exception as e:
                return _error(
                    400,
                    "invalid_metadata_json",
                    f"invalid metadata json: {e}",
                )

        content = await file.read()

        csv_opts = None
        if csv_has_header or csv_meta_cols or csv_include_cols:
            csv_opts = {
                "has_header": csv_has_header or "auto",
                "meta_cols": csv_meta_cols or "",
                "include_cols": csv_include_cols or "",
            }

        try:
            result = svc_ingest_document(
                store, tenant, collection, file.filename, content,
                docid, meta_obj, csv_options=csv_opts
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
            status_map = {"invalid_csv_options": 400, "ingest_failed": 500}
            return _error(
                status_map.get(code, 500),
                code,
                exc.message,
            )

    @app.delete(
        "/collections/{tenant}/{collection}/documents/{docid}",
        responses=_resp(401, 403, 500),
    )
    def delete_document(
        tenant: str,
        collection: str,
        docid: str,
        ctx: AuthContext = Depends(authorize_tenant),
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
        responses=_resp(401, 403, 500),
    )
    def search_post(
        tenant: str,
        name: str,
        body: SearchBody,
        x_request_id: str | None = Header(None, alias="X-Request-ID"),
        ctx: AuthContext = Depends(authorize_tenant),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        request_id = body.request_id or x_request_id
        include_common = bool(cfg.common_enabled)
        try:
            result = svc_search(
                store, tenant, name, body.q, body.k, filters=body.filters,
                include_common=include_common, common_tenant=cfg.common_tenant,
                common_collection=cfg.common_collection, request_id=request_id
            )
            return JSONResponse(result)
        except ServiceError as exc:
            return _error(500, exc.code, exc.message)

    # GET search (no filters)
    @app.get(
        "/collections/{tenant}/{name}/search",
        responses=_resp(401, 403, 500),
    )
    def search_get(
        tenant: str,
        name: str,
        q: str = Query(...),
        k: int = Query(5, ge=1),
        x_request_id: str | None = Header(None, alias="X-Request-ID"),
        ctx: AuthContext = Depends(authorize_tenant),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        include_common = bool(cfg.common_enabled)
        try:
            result = svc_search(
                store, tenant, name, q, k, filters=None,
                include_common=include_common, common_tenant=cfg.common_tenant,
                common_collection=cfg.common_collection, request_id=x_request_id
            )
            return JSONResponse(result)
        except ServiceError as exc:
            return _error(500, exc.code, exc.message)

    # Common collection search
    @app.post(
        "/search",
        responses=_resp(401, 403, 500),
    )
    def search_common_post(
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
        try:
            result = svc_search(
                store, cfg.common_tenant, cfg.common_collection, body.q, body.k,
                filters=body.filters, request_id=request_id
            )
            return JSONResponse(result)
        except ServiceError as exc:
            return _error(500, exc.code, exc.message)

    @app.get(
        "/search",
        responses=_resp(401, 403, 500),
    )
    def search_common_get(
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
        try:
            result = svc_search(
                store, cfg.common_tenant, cfg.common_collection, q, k,
                filters=None, request_id=x_request_id
            )
            return JSONResponse(result)
        except ServiceError as exc:
            return _error(500, exc.code, exc.message)

    return app

def main_srv():
    """
    HTTP server entrypoint.
    Precedence: CFG (reads env first) > defaults.
    """
    cfg = get_cfg()
    log = get_logger()
    log.info("Welcome to PatchVEC 🍰")
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
    log_level = str(cfg.get("server.log_level", "info"))

    if cfg.get("dev",0):
        log_level = "debug"
        cfg.set("server.log_level", log_level)
        log.setLevel(logging.DEBUG)

    # run server
    uvicorn.run("pave.main:app",
                host=host,
                port=port,
                reload=reload,
                workers=workers,
                log_level=log_level)

# Default app instance for `uvicorn pave.main:app`
app = build_app()

# UI attach (minimal)
from pave.ui import attach_ui
attach_ui(app)

if __name__ == "__main__":
    main_srv()
