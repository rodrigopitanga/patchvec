# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from pathlib import Path

from pave import cli as pvcli
from pave.config import get_cfg


def _mk_collection_dirs(base: Path, tenant: str, *collections: str) -> None:
    tenant_dir = base / f"t_{tenant}"
    tenant_dir.mkdir(parents=True, exist_ok=True)
    for c in collections:
        coll_dir = tenant_dir / f"c_{c}"
        coll_dir.mkdir(parents=True, exist_ok=True)
        # Create catalog.json so the collection is recognized
        (coll_dir / "catalog.json").write_text("{}")


def test_list_collections_api_sorted(client, tmp_path, monkeypatch):
    cfg = get_cfg()
    monkeypatch.setattr(cfg, "_cfg", {**cfg._cfg, "data_dir": str(tmp_path)})

    _mk_collection_dirs(tmp_path, "acme", "invoices", "contracts", "reports")

    r = client.get("/collections/acme")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["tenant"] == "acme"
    assert data["collections"] == ["contracts", "invoices", "reports"]
    assert data["count"] == 3


def test_list_collections_api_empty_tenant(client, tmp_path, monkeypatch):
    cfg = get_cfg()
    monkeypatch.setattr(cfg, "_cfg", {**cfg._cfg, "data_dir": str(tmp_path)})

    # Create tenant dir but no collections
    (tmp_path / "t_empty").mkdir(parents=True, exist_ok=True)

    r = client.get("/collections/empty")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["collections"] == []
    assert data["count"] == 0


def test_list_collections_api_nonexistent_tenant(client, tmp_path, monkeypatch):
    cfg = get_cfg()
    monkeypatch.setattr(cfg, "_cfg", {**cfg._cfg, "data_dir": str(tmp_path)})

    r = client.get("/collections/nonexistent")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["collections"] == []
    assert data["count"] == 0


def test_list_collections_cli(tmp_path, capsys, monkeypatch):
    from pave.stores.factory import get_store

    cfg = get_cfg()
    monkeypatch.setattr(cfg, "_cfg", {**cfg._cfg, "data_dir": str(tmp_path)})

    # Monkeypatch the store in cli module to use the new config
    store = get_store(cfg)
    monkeypatch.setattr(pvcli, "store", store)

    _mk_collection_dirs(tmp_path, "demo", "books", "articles")

    pvcli.main_cli(["list-collections", "demo"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["tenant"] == "demo"
    assert out["collections"] == ["articles", "books"]
    assert out["count"] == 2
