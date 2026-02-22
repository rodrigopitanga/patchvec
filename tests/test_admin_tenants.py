# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from fastapi.testclient import TestClient

from pave.config import get_cfg
from pave.main import build_app
from pave.ui import attach_ui


def _mk_tenant_dirs(base: Path, *tenants: str) -> None:
    for t in tenants:
        (base / f"t_{t}").mkdir(parents=True, exist_ok=True)


def test_admin_list_tenants_sorted(client, temp_data_dir):
    _mk_tenant_dirs(Path(temp_data_dir), "beta", "alpha")
    r = client.get("/admin/tenants")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["tenants"] == ["alpha", "beta"]
    assert data["count"] == 2


def test_admin_list_tenants_requires_admin(tmp_path):
    cfg = get_cfg()
    cfg.set("data_dir", str(tmp_path))
    cfg.set("auth.mode", "static")
    cfg.set("auth.global_key", "sekret")

    app = build_app(cfg)
    try:
        attach_ui(app)
    except Exception:
        pass

    client = TestClient(app)
    _mk_tenant_dirs(tmp_path, "acme")

    r = client.get("/admin/tenants")
    assert r.status_code == 401

    r = client.get("/admin/tenants", headers={"Authorization": "Bearer sekret"})
    assert r.status_code == 200
    assert r.json()["tenants"] == ["acme"]
