# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import shutil
import zipfile
from pathlib import Path

from pave.stores import txtai_store
from pave.service import create_data_archive


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


def test_create_data_archive_acquires_txtai_locks(monkeypatch, temp_data_dir):
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
    archive_path, tmp_dir = create_data_archive(store, temp_data_dir)
    try:
        assert ("acquire", "t_acme:c_invoices") in events
        assert ("release", "t_acme:c_invoices") in events
        assert Path(archive_path).is_file()
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

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
