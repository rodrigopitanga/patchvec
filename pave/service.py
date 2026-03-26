# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone as tz
from pathlib import Path
from collections.abc import Iterable, Iterator
from typing import Any

import time as _time
from pave.config import get_logger
from pave.metrics import (
    inc as m_inc, timed as m_timed, record_latency as m_record_latency
)
from pave.preprocess import preprocess
from pave.stores.base import BaseStore, MetadataValidationError, SearchResult

log = get_logger()

# Pure-ish service functions operating on a store adapter
class ServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def create_collection(store, tenant: str, name: str) -> dict[str, Any]:
    try:
        lock_cm = nullcontext()
        base_store = _unwrap_store(store)
        # TODO(P1-31): collection_lock moves to Store orchestrator;
        # remove isinstance guard and direct store-module import.
        try:
            from pave.stores.faiss import FaissStore, collection_lock
        except Exception:
            FaissStore = None  # type: ignore[assignment]
        if FaissStore is not None and isinstance(base_store, FaissStore):
            lock_cm = collection_lock(tenant, name)
        with lock_cm:
            store.load_or_init(tenant, name)
            store.save(tenant, name)
        m_inc("collections_created_total", 1.0)
        return {
            "ok": True,
            "tenant": tenant,
            "collection": name
        }
    except Exception as e:
        log.warning(
            "create_collection failed tenant=%s coll=%s: %s",
            tenant, name, e,
        )
        return {
            "ok": False,
            "code": "create_collection_failed",
            "error": str(e),
        }

def delete_collection(store, tenant: str, name: str) -> dict[str, Any]:
    try:
        store.delete_collection(tenant, name)
        m_inc("collections_deleted_total", 1.0)
        return {
            "ok": True,
            "tenant": tenant,
            "deleted": name
        }
    except Exception as e:
        log.warning(
            "delete_collection failed tenant=%s coll=%s: %s",
            tenant, name, e,
        )
        return {
            "ok": False,
            "code": "delete_collection_failed",
            "error": str(e),
        }

def rename_collection(store, tenant: str,
                      old_name: str, new_name: str) -> dict[str, Any]:
    if old_name == new_name:
        log.info(
            "rename_collection rejected tenant=%s: "
            "same name %s", tenant, old_name,
        )
        return {
            "ok": False,
            "code": "rename_invalid",
            "error": "old and new names are the same",
            "error_type": "invalid",
        }
    try:
        store.rename_collection(tenant, old_name, new_name)
        m_inc("collections_renamed_total", 1.0)
        return {
            "ok": True,
            "tenant": tenant,
            "old_name": old_name,
            "new_name": new_name
        }
    except ValueError as e:
        err = str(e)
        if "does not exist" in err:
            log.info(
                "rename_collection not_found tenant=%s "
                "old=%s: %s", tenant, old_name, err,
            )
            return {
                "ok": False,
                "code": "collection_not_found",
                "error": err,
                "error_type": "not_found",
            }
        if "already exists" in err:
            log.info(
                "rename_collection conflict tenant=%s "
                "new=%s: %s", tenant, new_name, err,
            )
            return {
                "ok": False,
                "code": "collection_conflict",
                "error": err,
                "error_type": "conflict",
            }
        log.info(
            "rename_collection invalid tenant=%s "
            "old=%s new=%s: %s",
            tenant, old_name, new_name, err,
        )
        return {
            "ok": False,
            "code": "rename_invalid",
            "error": err,
            "error_type": "invalid",
        }
    except Exception as e:
        log.warning(
            "rename_collection failed tenant=%s "
            "old=%s new=%s: %s",
            tenant, old_name, new_name, e,
        )
        return {
            "ok": False,
            "code": "rename_failed",
            "error": str(e),
            "error_type": "failed",
        }

def delete_document(store, tenant: str, collection: str, docid: str) -> dict[str, Any]:
    try:
        if store.has_doc(tenant, collection, docid):
            purged = store.purge_doc(tenant, collection, docid)
            m_inc("purge_total", float(purged))
            m_inc("documents_deleted_total", 1.0)
        else:
            purged = 0
        return {
            "ok": True,
            "tenant": tenant,
            "collection": collection,
            "docid": docid,
            "chunks_deleted": purged,
        }
    except Exception as e:
        log.warning(
            "delete_document failed tenant=%s coll=%s "
            "docid=%s: %s", tenant, collection, docid, e,
        )
        return {
            "ok": False,
            "code": "delete_document_failed",
            "error": str(e),
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
                    docid: str | None, metadata: dict[str, Any] | None,
                    csv_options: dict[str, Any] | None = None) -> dict[str, Any]:
    _t0 = _time.perf_counter()
    with m_timed("ingest"):
        try:
            baseid = docid or _default_docid(filename)
            if baseid and store.has_doc(tenant, collection, baseid):
                purged = store.purge_doc(tenant, collection, baseid)
                m_inc("purge_total", purged)
            meta_from_call = metadata or {}
            now = datetime.now(tz.utc).isoformat(timespec="seconds")
            now = now.replace("+00:00", "Z")
            doc_meta = {
                "docid": baseid, "filename": filename,
                "ingested_at": now, **meta_from_call,
            }
            records = []
            for local_id, text, extra in preprocess(
                filename, content, csv_options=csv_options
            ):
                rid = f"{baseid}::{local_id}"
                records.append((rid, text, extra))
            if not records:
                log.info(
                    "ingest no_text_extracted tenant=%s "
                    "coll=%s file=%s",
                    tenant, collection, filename,
                )
                return {
                    "ok": False,
                    "code": "no_text_extracted",
                    "error": "no text extracted",
                }
            count = store.index_records(tenant, collection, baseid, records, doc_meta)
            m_inc("documents_indexed_total", 1.0)
            m_inc("chunks_indexed_total", float(count or 0))
            latency_ms = round((_time.perf_counter() - _t0) * 1000, 2)
            log.info(
                f"ingest tenant={tenant} coll={collection} "
                f"docid={baseid} chunks={count} ms={latency_ms:.2f}"
            )
            return {
                "ok": True,
                "tenant": tenant,
                "collection": collection,
                "docid": baseid,
                "chunks": count
            }
        except ServiceError:
            raise
        except MetadataValidationError as exc:
            raise ServiceError("invalid_metadata_keys", str(exc)) from exc
        except ValueError as exc:
            raise ServiceError("invalid_csv_options", str(exc)) from exc
        except Exception as e:
            log.warning(
                "ingest failed tenant=%s coll=%s "
                "docid=%s: %s",
                tenant, collection,
                docid or filename, e,
            )
            return {
                "ok": False,
                "code": "ingest_failed",
                "error": str(e),
            }

def search(store, tenant: str, collection: str, q: str, k: int = 5,
              filters: dict[str, Any] | None = None, include_common: bool = False,
              common_tenant: str | None = None, common_collection: str | None = None,
              request_id: str | None = None
              ) -> dict[str, Any]:
    start = _time.perf_counter()
    m_inc("search_total", 1.0)
    try:
        if include_common and common_tenant and common_collection:
            matches: list[SearchResult] = []
            matches.extend(store.search(
                tenant, collection, q, max(10, k * 2), filters=filters))
            matches.extend(store.search(
                common_tenant, common_collection, q, max(10, k * 2),
                filters=filters))
            from heapq import nlargest
            top = nlargest(k, matches, key=lambda x: x.score)
            m_inc("matches_total", float(len(top) or 0))
            latency_ms = round((_time.perf_counter() - start) * 1000, 2)
            m_record_latency("search", latency_ms)
            _t = top[0] if top else None
            log.info(
                f"search tenant={tenant} coll={collection} k={k} "
                f"hits={len(top)} ms={latency_ms:.2f}"
                + (f" top=[{_t.id} {_t.score:.3f}] \"{(_t.text or '')[:60]}{'...' if len(_t.text or '') > 60 else ''}\"" if _t else "")
                + (f" req={request_id}" if request_id else ""))
            return {
                "matches": [r.to_dict() for r in top],
                "latency_ms": latency_ms,
                "request_id": request_id,
            }
        top = store.search(tenant, collection, q, k, filters=filters)
        m_inc("matches_total", float(len(top) or 0))
        latency_ms = round((_time.perf_counter() - start) * 1000, 2)
        m_record_latency("search", latency_ms)
        _t = top[0] if top else None
        log.info(
            f"search tenant={tenant} coll={collection} k={k} "
            f"hits={len(top)} ms={latency_ms:.2f}"
            + (f" top=[{_t.id} {_t.score:.3f}] \"{(_t.text or '')[:60]}{'...' if len(_t.text or '') > 60 else ''}\"" if _t else "")
            + (f" req={request_id}" if request_id else ""))
        return {
            "matches": [r.to_dict() for r in top],
            "latency_ms": latency_ms,
            "request_id": request_id,
        }
    except Exception as exc:
        raise ServiceError("search_failed", str(exc)) from exc


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
                try:
                    zf.write(file_path, rel_name.as_posix())
                except FileNotFoundError:
                    # TOCTOU: file vanished between os.walk and zf.write.
                    continue
                except OSError as exc:
                    if exc.errno == errno.ENOENT:
                        continue
                    raise


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


def _flush_store_caches(
    store: BaseStore | None,
    *,
    async_close: bool = True,
) -> None:
    """Drop all in-memory CollectionDB and backend references.

    Called after restore_archive replaces files on disk so that the next
    access re-opens fresh connections from the restored files.

    When ``async_close`` is True old CollectionDB instances are closed in
    a daemon thread. Restore path uses ``async_close=False`` so DB handles
    are closed before filesystem replacement starts.
    """
    base_store = _unwrap_store(store)
    if base_store is None:
        return
    try:
        from pave.stores.faiss import FaissStore  # type: ignore
    except Exception:
        return
    if not isinstance(base_store, FaissStore):
        return

    old_dbs = list(base_store._dbs.values())
    base_store._dbs.clear()
    base_store._emb.clear()

    if not old_dbs:
        return

    def _close_all() -> None:
        for db in old_dbs:
            try:
                db.close()
            except Exception:
                pass

    if async_close:
        import threading
        threading.Thread(target=_close_all, daemon=True).start()
    else:
        _close_all()


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
    """Yield lock keys for ``FaissStore`` directory layout."""

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
    """Acquire all known collection locks for ``FaissStore`` instances."""

    base_store = _unwrap_store(store)
    if base_store is None:
        yield
        return

    # TODO(P1-31): archive locking moves to Store orchestrator;
    # remove direct _LOCKS/_LOCKS_GUARD access.
    try:
        from threading import Lock as _Lock
        from pave.stores import faiss as store_mod  # type: ignore
        FaissStore = store_mod.FaissStore
    except Exception:
        yield
        return

    if not isinstance(base_store, FaissStore):
        yield
        return

    guard = store_mod._LOCKS_GUARD
    locks = []
    guard.acquire()
    try:
        keys = set(_iter_collection_lock_keys(data_dir))
        keys.update(store_mod._LOCKS.keys())
        for key in sorted(keys):
            if key not in store_mod._LOCKS:
                store_mod._LOCKS[key] = _Lock()
            lock = store_mod._LOCKS[key]
            lock.acquire()
            locks.append(lock)
        yield
    finally:
        for lock in reversed(locks):
            lock.release()
        guard.release()


def _remove_path(path: Path, *, retries: int = 4) -> None:
    """Best-effort removal with short retries for transient directory races."""

    for attempt in range(retries):
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            transient = {
                errno.ENOENT,
                errno.ENOTEMPTY,
                errno.EBUSY,
            }
            if exc.errno in transient and attempt < (retries - 1):
                _time.sleep(0.02 * (attempt + 1))
                continue
            raise


def dump_archive(
        store: BaseStore | None, data_dir: str | os.PathLike[str],
        output_path: str | os.PathLike[str | None] = None,
) -> tuple[str, str | None]:
    """Create a ZIP archive containing the contents of ``data_dir``.

    Parameters
    ----------
    store:
        Optional vector-store implementation. When provided and it maps to a
        ``FaissStore`` backend all known collection locks are acquired for the
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
    tuple[str, str | None]
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


def restore_archive(
        store: BaseStore | None, data_dir: str | os.PathLike[str],
        archive_bytes: bytes
) -> dict[str, Any]:
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
            _flush_store_caches(store, async_close=False)

            for entry in data_dir_path.iterdir():
                _remove_path(entry)

            for entry in extract_dir.iterdir():
                target = data_dir_path / entry.name
                if target.exists() or target.is_symlink():
                    _remove_path(target)
                shutil.move(str(entry), str(target))

    return {"ok": True, "data_dir": str(data_dir_path)}


def list_tenants(store, data_dir: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        tenants = sorted(store.list_tenants(str(data_dir)))
        return {
            "ok": True,
            "tenants": tenants,
            "count": len(tenants),
        }
    except Exception as e:
        log.warning("list_tenants failed: %s", e)
        return {
            "ok": False,
            "code": "list_tenants_failed",
            "error": str(e),
        }

def list_collections(store, tenant: str) -> dict[str, Any]:
    try:
        collections = sorted(store.list_collections(tenant))
        return {
            "ok": True,
            "tenant": tenant,
            "collections": collections,
            "count": len(collections),
        }
    except Exception as e:
        log.warning(
            "list_collections failed tenant=%s: %s",
            tenant, e,
        )
        return {
            "ok": False,
            "code": "list_collections_failed",
            "error": str(e),
        }
