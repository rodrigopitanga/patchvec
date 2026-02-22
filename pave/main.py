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
    search as svc_search
from pave.schemas import SearchBody, RenameCollectionBody, SearchResponse


VERSION = "0.5.7"

# Dependency injection builder
def build_app(cfg=get_cfg()) -> FastAPI:

    log = get_logger()

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

    @app.get("/admin/archive", response_class=FileResponse)
    async def dump_archive(
        ctx: AuthContext = Depends(auth_ctx),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        if not ctx.is_admin:
            raise HTTPException(status_code=403, detail="admin access required")

        data_dir = cfg.get("data_dir")
        if not data_dir:
            raise HTTPException(
                status_code=500, detail="data directory is not configured")

        try:
            archive_path, tmp_dir = await run_in_threadpool(
                svc_dump_archive, store, data_dir
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail="data directory not found")
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"failed to dump archive: {exc}")

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

    @app.put("/admin/archive")
    async def restore_archive(
        ctx: AuthContext = Depends(auth_ctx),
        store: BaseStore = Depends(current_store),
        file: UploadFile = File(...),
    ):
        inc("requests_total")
        if not ctx.is_admin:
            raise HTTPException(status_code=403, detail="admin access required")

        data_dir = cfg.get("data_dir")
        if not data_dir:
            raise HTTPException(
                status_code=500, detail="data directory is not configured")

        content = await file.read()
        try:
            out = await run_in_threadpool(
                svc_restore_archive, store, data_dir, content
            )
            return out
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"failed to restore archive: {exc}")

    @app.delete("/admin/metrics")
    def delete_metrics(
        ctx: AuthContext = Depends(auth_ctx),
    ):
        inc("requests_total")
        if not ctx.is_admin:
            raise HTTPException(status_code=403, detail="admin access required")
        return metrics_reset()

    @app.get("/admin/tenants")
    def list_tenants(
        ctx: AuthContext = Depends(auth_ctx),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        if not ctx.is_admin:
            raise HTTPException(status_code=403, detail="admin access required")
        data_dir = cfg.get("data_dir")
        if not data_dir:
            raise HTTPException(
                status_code=500, detail="data directory is not configured")
        result = svc_list_tenants(store, data_dir)
        if not result.get("ok"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "failed to list tenants"))
        return result

    @app.get("/collections/{tenant}")
    def list_collections(
        tenant: str,
        ctx: AuthContext = Depends(authorize_tenant),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        result = svc_list_collections(store, tenant)
        if not result.get("ok"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "failed to list collections"))
        return result

    @app.post("/collections/{tenant}/{name}")
    def create_collection(
        tenant: str,
        name: str,
        ctx: AuthContext = Depends(authorize_tenant),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        return svc_create_collection(store, tenant, name)

    @app.delete("/collections/{tenant}/{name}")
    def delete_collection(
        tenant: str,
        name: str,
        ctx: AuthContext = Depends(authorize_tenant),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        return svc_delete_collection(store, tenant, name)

    @app.put("/collections/{tenant}/{name}")
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
            err = result.get("error", "unknown error")
            raise HTTPException(
                status_code=400, detail=f"failed to rename collection: {err}")
        return result

    @app.post("/collections/{tenant}/{collection}/documents")
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
                raise HTTPException(
                    status_code=400,
                    detail=f"invalid metadata json: {e}"
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
            out = svc_ingest_document(
                store, tenant, collection, file.filename, content,
                docid, meta_obj, csv_options=csv_opts
            )
            return out
        except ValueError as ve:
            # e.g., names provided but no header
            raise HTTPException(status_code=400, detail=str(ve))

    @app.delete("/collections/{tenant}/{collection}/documents/{docid}")
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
            raise HTTPException(
                status_code=404,
                detail=result.get("error", "document not found"))
        return result

    # POST search (supports filters)
    @app.post("/collections/{tenant}/{name}/search", response_model=SearchResponse)
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
        result = svc_search(
            store, tenant, name, body.q, body.k, filters=body.filters,
            include_common=include_common, common_tenant=cfg.common_tenant,
            common_collection=cfg.common_collection, request_id=request_id
        )
        return JSONResponse(result)

    # GET search (no filters)
    @app.get("/collections/{tenant}/{name}/search")
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
        result = svc_search(
            store, tenant, name, q, k, filters=None,
            include_common=include_common, common_tenant=cfg.common_tenant,
            common_collection=cfg.common_collection, request_id=x_request_id
        )
        return JSONResponse(result)

    # Common collection search
    @app.post("/search")
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
        result = svc_search(
            store, cfg.common_tenant, cfg.common_collection, body.q, body.k,
            filters=body.filters, request_id=request_id
        )
        return JSONResponse(result)

    @app.get("/search")
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
        result = svc_search(
            store, cfg.common_tenant, cfg.common_collection, q, k, filters=None,
            request_id=x_request_id
        )
        return JSONResponse(result)

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
