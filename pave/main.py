# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import json, os
from fastapi import FastAPI, Header, Body, File, UploadFile, Form, Path, Query, Depends, Request, \
    HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, Annotated
import uvicorn
from .config import CFG
from .auth import AuthContext, auth_ctx, authorize_tenant, enforce_policy, resolve_bind
from .metrics import inc, set_error, snapshot, to_prometheus
from .stores.factory import get_store
from .stores.base import BaseStore
from .service import create_collection as svc_create_collection, delete_collection as svc_delete_collection, \
    ingest_document as svc_ingest_document, do_search as svc_do_search


VERSION = "0.5.6dev3"

class SearchBody(BaseModel):
    q: str
    k: int = 5
    filters: Optional[Dict[str, Any]] = None

# Dependency injection builder

def build_app(cfg=CFG) -> FastAPI:
    app = FastAPI(title="PatchVec — Vector Search (pluggable, functional)")
    app.state.store = get_store(cfg)

    def current_store(request: Request) -> BaseStore:
        return request.app.state.store


    # -------------------- Health --------------------

    def _readiness_check() -> Dict[str, Any]:
        details: Dict[str, Any] = {
            "data_dir": cfg.data_dir,
            "vector_store_type": cfg.get("vector_store.type", "txtai"),
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
        details["ok"] = bool(details["writable"] and details["vector_backend_init"])
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
        extra = {"version": VERSION, "vector_store_type": cfg.get("vector_store.type", "txtai")}
        return snapshot(extra)

    @app.get("/metrics")
    def metrics_prom():
        inc("requests_total")
        txt = to_prometheus(build={"version": VERSION, "store": cfg.get("vector_store.type", "txtai")})
        return PlainTextResponse(txt, media_type="text/plain; version=0.0.4")

    
    # ----------------- Core API ------------------

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
    def delete_collection_route(
        tenant: str,
        name: str,
        ctx: AuthContext = Depends(authorize_tenant),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        return svc_delete_collection(store, tenant, name)

    @app.post("/collections/{tenant}/{collection}/documents")
    async def upload_document(
        tenant: str,
        collection: str,
        file: UploadFile = File(...),
        docid: Optional[str] = Form(None),
        metadata: Optional[str] = Form(None),
        # CSV controls as optional query params (kept out of form to not clash with file upload)
        csv_has_header: Optional[str] = Query(None, pattern="^(auto|yes|no)$"),
        csv_meta_cols: Optional[str] = Query(None),
        csv_include_cols: Optional[str] = Query(None),
        ctx: AuthContext = Depends(authorize_tenant),
        store: BaseStore = Depends(current_store),
    ):
        meta_obj = None
        if metadata:
            try:
                import json
                meta_obj = json.loads(metadata)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"invalid metadata json: {e}")

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

    # POST search (supports filters)
    @app.post("/collections/{tenant}/{name}/search")
    def search_route_post(
        tenant: str,
        name: str,
        body: SearchBody,
        ctx: AuthContext = Depends(authorize_tenant),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        include_common = bool(cfg.common_enabled)
        result = svc_do_search(
            store, tenant, name, body.q, body.k, filters=body.filters,
            include_common=include_common, common_tenant=cfg.common_tenant, common_collection=cfg.common_collection
        )
        return JSONResponse(result)

    # GET search (no filters)
    @app.get("/collections/{tenant}/{name}/search")
    def search_route_get(
        tenant: str,
        name: str,
        q: str = Query(...),
        k: int = Query(5, ge=1),
        ctx: AuthContext = Depends(authorize_tenant),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        include_common = bool(cfg.common_enabled)
        result = svc_do_search(
            store, tenant, name, q, k, filters=None,
            include_common=include_common, common_tenant=cfg.common_tenant, common_collection=cfg.common_collection
        )
        return JSONResponse(result)

    # Common collection search
    @app.post("/search")
    def search_common_post(
        body: SearchBody,
        ctx: AuthContext = Depends(auth_ctx),
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        if not cfg.common_enabled:
            return JSONResponse({"matches": []})
        result = svc_do_search(store, cfg.common_tenant, cfg.common_collection, body.q, body.k, filters=body.filters)
        return JSONResponse(result)

    @app.get("/search")
    def search_common_get(
        q: str = Query(...),
        k: int = Query(5, ge=1),
        ctx: AuthContext = Depends(auth_ctx), 
        store: BaseStore = Depends(current_store),
    ):
        inc("requests_total")
        if not cfg.common_enabled:
            return JSONResponse({"matches": []})
        result = svc_do_search(store, cfg.common_tenant, cfg.common_collection, q, k, filters=None)
        return JSONResponse(result)

    return app

def main_srv():
    """
    PatchVec server entrypoint.
    Precedence: CFG (reads env first) > defaults.
    """
    
    # Policy:
    # - fail fast without auth in prod;
    # - auth=none only in dev with loopback;
    # - raises on invalid config.
    enforce_policy(CFG)

    # resolve bind host/port
    host, port = resolve_bind(CFG)

    # flags from CFG
    reload = bool(CFG.get("server.reload", False))
    workers = int(CFG.get("server.workers", 1))
    log_level = str(CFG.get("server.log_level", "info"))

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
attach_ui(app, CFG, VERSION)

if __name__ == "__main__":
    main_srv()
