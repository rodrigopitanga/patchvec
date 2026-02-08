# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone as tz
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import time as _time
from pave.config import get_logger
from pave.metrics import inc as m_inc, timed as m_timed, record_latency as m_record_latency
from pave.preprocess import preprocess
from pave.stores.base import BaseStore

_log = get_logger()

# Pure-ish service functions operating on a store adapter

def create_collection(store, tenant: str, name: str) -> Dict[str, Any]:
    store.load_or_init(tenant, name)
    store.save(tenant, name)
    m_inc("collections_created_total", 1.0)
    return {
        "ok": True,
        "tenant": tenant,
        "collection": name
    }

def delete_collection(store, tenant: str, name: str) -> Dict[str, Any]:
    store.delete_collection(tenant, name)
    m_inc("collections_deleted_total", 1.0)
    return {
        "ok": True,
        "tenant": tenant,
        "deleted": name
    }

def delete_document(store, tenant: str, collection: str, docid: str) -> Dict[str, Any]:
    if not store.has_doc(tenant, collection, docid):
        return {
            "ok": False,
            "error": "document not found",
            "tenant": tenant,
            "collection": collection,
            "docid": docid
        }
    purged = store.purge_doc(tenant, collection, docid)
    m_inc("purge_total", float(purged))
    m_inc("documents_deleted_total", 1.0)
    return {
        "ok": True,
        "tenant": tenant,
        "collection": collection,
        "docid": docid,
        "chunks_deleted": purged
    }

def _default_docid(filename: str) -> str:
    # Uppercase
    base = filename.upper()
    # replace space and dot with underscore
    base = base.replace(" ", "_").replace(".", "_")
    # replace all non A-Z0-9_ with underscore
    base = re.sub(r"[^A-Z0-9_]", "_", base)
    # collapse multiple underscores
    base = re.sub(r"_+", "_", base).strip("_")
    if base != '': return base
    return "PVDOC_"+str(uuid.uuid4())

def ingest_document(store, tenant: str, collection: str, filename: str, content: bytes,
                    docid: str | None, metadata: Dict[str, Any] | None,
                    csv_options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    with m_timed("ingest"):
        baseid = docid or _default_docid(filename)
        if baseid and store.has_doc(tenant, collection, baseid):
            purged = store.purge_doc(tenant, collection, baseid)
            m_inc("purge_total", purged)
        meta_doc = metadata or {}
        records = []
        for local_id, text, extra in preprocess(filename, content, csv_options=csv_options):
            rid = f"{baseid}::{local_id}"
            now = datetime.now(tz.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            meta = {"docid": baseid, "filename": filename, "ingested_at": now}
            meta.update(meta_doc)
            meta.update(extra)
            records.append((rid, text, meta))
        if not records:
            return {"ok": False, "error": "no text extracted"}
        count = store.index_records(tenant, collection, baseid, records)
        m_inc("documents_indexed_total", 1.0)
        m_inc("chunks_indexed_total", float(count or 0))
        return {
            "ok": True,
            "tenant": tenant,
            "collection": collection,
            "docid": baseid,
            "chunks": count
        }

def do_search(store, tenant: str, collection: str, q: str, k: int = 5,
              filters: Dict[str, Any] | None = None, include_common: bool = False,
              common_tenant: str | None = None, common_collection: str | None = None,
              request_id: str | None = None
              ) -> Dict[str, Any]:
    start = _time.perf_counter()
    m_inc("search_total", 1.0)
    if include_common and common_tenant and common_collection:
        matches: List[Dict[str, Any]] = []
        matches.extend(store.search(
            tenant, collection, q, max(10, k * 2), filters=filters))
        matches.extend(store.search(
            common_tenant, common_collection, q, max(10, k * 2), filters=filters))
        from heapq import nlargest
        top = nlargest(k, matches, key=lambda x: x["score"])
        m_inc("matches_total", float(len(top) or 0))
        latency_ms = round((_time.perf_counter() - start) * 1000, 2)
        m_record_latency("search", latency_ms)
        _log.info("search tenant=%s collection=%s k=%d hits=%d latency_ms=%.2f request_id=%s",
                  tenant, collection, k, len(top), latency_ms, request_id)
        return {"matches": top, "latency_ms": latency_ms, "request_id": request_id}
    top = store.search(tenant, collection, q, k, filters=filters)
    m_inc("matches_total", float(len(top) or 0))
    latency_ms = round((_time.perf_counter() - start) * 1000, 2)
    m_record_latency("search", latency_ms)
    _log.info("search tenant=%s collection=%s k=%d hits=%d latency_ms=%.2f request_id=%s",
              tenant, collection, k, len(top), latency_ms, request_id)
    return {
        "matches": top,
        "latency_ms": latency_ms,
        "request_id": request_id
    }


def _write_zip(source_dir: Path, target_path: Path) -> None:
    """Create a ZIP archive at ``target_path`` with the contents of ``source_dir``."""

    source_dir = source_dir.resolve()
    target_path = target_path.resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"data directory not found: {source_dir}")

    target_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            root_path = Path(root)
            rel_root = root_path.relative_to(source_dir)

            # Preserve empty directories
            if not files and not dirs:
                arcname = str(rel_root) + "/" if rel_root != Path('.') else ""
                if arcname:
                    zf.writestr(arcname, "")
                continue

            for filename in files:
                file_path = root_path / filename
                rel_name = file_path.relative_to(source_dir)
                zf.write(file_path, rel_name.as_posix())


def _validate_zip_members(zf: zipfile.ZipFile) -> None:
    for member in zf.infolist():
        name = member.filename
        if not name:
            continue
        rel_path = Path(name)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValueError(f"invalid archive member: {name}")
        if name.startswith(("/", "\\")):
            raise ValueError(f"invalid archive member: {name}")


def _unwrap_store(store: BaseStore | None) -> BaseStore | None:
    """Follow ``impl`` attributes to reach the concrete store implementation."""

    seen: set[int] = set()
    current = store
    while isinstance(current, BaseStore) and hasattr(current, "impl"):
        impl = getattr(current, "impl")
        if not isinstance(impl, BaseStore):
            break
        ident = id(impl)
        if ident in seen:
            break
        seen.add(ident)
        current = impl
    return current


def _iter_collection_lock_keys(data_dir: Path) -> Iterable[str]:
    """Yield lock keys for ``TxtaiStore``-style directory layout."""

    for tenant_dir in data_dir.iterdir():
        if not tenant_dir.is_dir() or not tenant_dir.name.startswith("t_"):
            continue
        tenant = tenant_dir.name[2:]
        if not tenant:
            continue
        for coll_dir in tenant_dir.iterdir():
            if not coll_dir.is_dir() or not coll_dir.name.startswith("c_"):
                continue
            collection = coll_dir.name[2:]
            if not collection:
                continue
            yield f"t_{tenant}:c_{collection}"


@contextmanager
def _lock_indexes(store: BaseStore | None, data_dir: Path) -> Iterator[None]:
    """Acquire all known collection locks for ``TxtaiStore`` implementations."""

    base_store = _unwrap_store(store)
    if base_store is None:
        yield
        return

    try:
        from pave.stores.txtai_store import TxtaiStore, get_lock  # type: ignore
    except Exception:
        yield
        return

    if not isinstance(base_store, TxtaiStore):
        yield
        return

    keys = sorted(set(_iter_collection_lock_keys(data_dir)))
    if not keys:
        yield
        return

    locks = []
    for key in keys:
        lock = get_lock(key)
        lock.acquire()
        locks.append(lock)

    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


def create_data_archive(
        store: BaseStore | None, data_dir: str | os.PathLike[str],
        output_path: Optional[str | os.PathLike[str]] = None,
) -> Tuple[str, Optional[str]]:
    """Create a ZIP archive containing the contents of ``data_dir``.

    Parameters
    ----------
    store:
        Optional vector-store implementation. When provided and it maps to a
        ``TxtaiStore`` backend all known collection locks are acquired for the
        duration of the archive creation to avoid concurrent writes during the
        export.
    data_dir:
        Directory whose contents should be compressed.
    output_path:
        Optional explicit path for the resulting archive. When omitted a
        temporary directory is created and the caller is responsible for the
        lifetime of that directory.

    Returns
    -------
    tuple[str, Optional[str]]
        The first element is the absolute path to the generated archive. The
        second element is the temporary directory that owns the archive (or
        ``None`` when ``output_path`` was provided).
    """

    data_dir_path = Path(data_dir).resolve()
    if not data_dir_path.is_dir():
        raise FileNotFoundError(f"data directory not found: {data_dir_path}")

    if output_path is not None:
        archive_path = Path(output_path).resolve()
        with _lock_indexes(store, data_dir_path):
            _write_zip(data_dir_path, archive_path)
        return str(archive_path), None

    tmp_dir = Path(tempfile.mkdtemp(prefix="patchvec_export_"))
    timestamp = datetime.now(tz.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = tmp_dir / f"patchvec-data-{timestamp}.zip"
    with _lock_indexes(store, data_dir_path):
        _write_zip(data_dir_path, archive_path)
    return str(archive_path), str(tmp_dir)


def restore_data_archive(
        store: BaseStore | None, data_dir: str | os.PathLike[str],
        archive_bytes: bytes
) -> Dict[str, Any]:
    data_dir_path = Path(data_dir).resolve()
    data_dir_path.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="patchvec_import_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        archive_path = tmp_path / "patchvec-data.zip"
        extract_dir = tmp_path / "extracted"
        archive_path.write_bytes(archive_bytes)
        extract_dir.mkdir()

        with zipfile.ZipFile(archive_path, "r") as zf:
            _validate_zip_members(zf)
            zf.extractall(extract_dir)

        with _lock_indexes(store, data_dir_path):
            for entry in data_dir_path.iterdir():
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()

            for entry in extract_dir.iterdir():
                shutil.move(str(entry), data_dir_path / entry.name)

    return {"ok": True, "data_dir": str(data_dir_path)}

