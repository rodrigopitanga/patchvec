# Covers: 401 (no header), 403 (bad token), 200 (good token), tenant mismatch

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

def build_app():
    from pave.auth import authorize_tenant
    app = FastAPI()

    @app.post("/collections/{tenant}/{name}")
    def create_collection(tenant: str, name: str, ctx = Depends(authorize_tenant)):
        # If we reached here, auth passed for this tenant
        return {"ok": True, "tenant": tenant, "name": name}

    return app

@pytest.fixture(autouse=True)
def patch_cfg(monkeypatch, tmp_path):
    from pave import config as cfg_mod
    class DummyCFG:
        data_dir = str(tmp_path / "data")
        def get(self, key, default=None):
            # auth.* keys read by your code
            if key == "auth.mode":
                return "static"
            if key == "auth.global_key":
                return None  # default no global; test both modes below
            if key == "auth.api_keys":
                return {"acme": "sekret"}  # per-tenant mode
            return default
    monkeypatch.setattr(cfg_mod, "CFG", DummyCFG(), raising=True)
    yield

def test_static_auth_per_tenant():
    app = build_app()
    client = TestClient(app)

    # 401: no header
    r = client.post("/collections/acme/invoices")
    assert r.status_code == 401

    # 403: bad token
    r = client.post("/collections/acme/invoices", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 403

    # 200: correct per-tenant token on the same tenant path
    r = client.post("/collections/acme/invoices", headers={"Authorization": "Bearer sekret"})
    assert r.status_code == 200
    assert r.json()["tenant"] == "acme"

    # 403: tenant mismatch (token is for 'acme' but URL tenant is 'other')
    r = client.post("/collections/other/invoices", headers={"Authorization": "Bearer sekret"})
    assert r.status_code == 403

def test_static_auth_global_key(monkeypatch):
    # Reconfigure to use global key instead of per-tenant keys
    from pave import config as cfg_mod
    class CFGGlobal:
        data_dir = "/tmp"
        def get(self, key, default=None):
            if key == "auth.mode":
                return "static"
            if key == "auth.global_key":
                return "topsekret"  # global key active
            if key == "auth.api_keys":
                return None
            return default
    monkeypatch.setattr(cfg_mod, "CFG", CFGGlobal(), raising=True)

    app = build_app()
    client = TestClient(app)

    # Any tenant should accept the same global token
    for tenant in ("acme", "other"):
        r = client.post(f"/collections/{tenant}/invoices", headers={"Authorization": "Bearer topsekret"})
        assert r.status_code == 200
        assert r.json()["tenant"] == tenant
