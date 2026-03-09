# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

import io
import shutil
import threading
import zipfile
from pathlib import Path

from pave.stores import txtai_store
from pave.service import create_collection, dump_archive, _flush_store_caches


def test_dump_endpoint_returns_zip(client, temp_data_dir):
    sample = Path(temp_data_dir) / "tenant" / "collection" / "doc.txt"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text("hello endpoint", encoding="utf-8")

    response = client.get("/admin/archive")

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("application/zip")

    buffer = io.BytesIO(response.content)
    with zipfile.ZipFile(buffer) as zf:
        names = set(zf.namelist())
        assert "tenant/collection/doc.txt" in names
        with zf.open("tenant/collection/doc.txt") as f:
            assert f.read().decode("utf-8") == "hello endpoint"


def test_dump_archive_acquires_txtai_locks(monkeypatch, temp_data_dir):
    tenant_dir = Path(temp_data_dir) / "t_acme"
    collection_dir = tenant_dir / "c_invoices"
    collection_dir.mkdir(parents=True, exist_ok=True)
    sample = collection_dir / "doc.txt"
    sample.write_text("lock me", encoding="utf-8")

    events: list[tuple[str, str]] = []

    class SpyLock:
        def __init__(self, key: str) -> None:
            self.key = key

        def acquire(self) -> bool:
            events.append(("acquire", self.key))
            return True

        def release(self) -> None:
            events.append(("release", self.key))

    locks: dict[str, SpyLock] = {}

    def fake_get_lock(key: str) -> SpyLock:
        locks.setdefault(key, SpyLock(key))
        return locks[key]

    monkeypatch.setattr(txtai_store, "get_lock", fake_get_lock)

    store = txtai_store.TxtaiStore()
    archive_path, tmp_dir = dump_archive(store, temp_data_dir)
    try:
        assert ("acquire", "t_acme:c_invoices") in events
        assert ("release", "t_acme:c_invoices") in events
        assert Path(archive_path).is_file()
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

def test_flush_store_caches_closes_old_dbs():
    """_flush_store_caches closes abandoned CollectionDB instances."""
    store = txtai_store.TxtaiStore()
    store.index_records(
        "acme", "flush_test", "doc1",
        [("0", "flush probe", {"lang": "en"})],
    )
    key = ("acme", "flush_test")
    col_db = store._dbs[key]

    # Verify DB is open
    assert col_db._rconn is not None

    _flush_store_caches(store)

    # Caches are cleared immediately
    assert key not in store._dbs
    assert key not in store._emb

    # Wait for daemon thread to close the DB
    for t in threading.enumerate():
        if t.daemon and t.is_alive():
            t.join(timeout=2.0)

    assert col_db._rconn is None
    assert col_db._wconn is None


def test_create_collection_uses_collection_lock(monkeypatch):
    store = txtai_store.TxtaiStore()
    events: list[tuple[str, str, str]] = []

    class _SpyLock:
        def __init__(self, tenant: str, collection: str) -> None:
            self.tenant = tenant
            self.collection = collection

        def __enter__(self):
            events.append(("enter", self.tenant, self.collection))
            return self

        def __exit__(self, exc_type, exc, tb):
            events.append(("exit", self.tenant, self.collection))
            return False

    def fake_collection_lock(tenant: str, collection: str):
        return _SpyLock(tenant, collection)

    monkeypatch.setattr(
        txtai_store,
        "collection_lock",
        fake_collection_lock,
    )

    out = create_collection(store, "acme", "locked")
    assert out["ok"] is True
    assert ("enter", "acme", "locked") in events
    assert ("exit", "acme", "locked") in events


def test_restore_endpoint_replaces_data_dir(client, temp_data_dir):
    sample = Path(temp_data_dir) / "tenant" / "collection" / "doc.txt"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text("restore me", encoding="utf-8")

    response = client.get("/admin/archive")
    assert response.status_code == 200

    shutil.rmtree(temp_data_dir)
    Path(temp_data_dir).mkdir(parents=True, exist_ok=True)
    other = Path(temp_data_dir) / "other.txt"
    other.write_text("doomed", encoding="utf-8")

    put = client.put(
        "/admin/archive",
        files={"file": ("dump.zip", response.content, "application/zip")},
    )

    assert put.status_code == 200
    assert put.json()["ok"] is True
    assert sample.exists()
    assert sample.read_text(encoding="utf-8") == "restore me"
    assert not other.exists()
