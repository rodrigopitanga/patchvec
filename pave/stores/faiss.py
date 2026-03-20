# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations
import os, json, operator, tempfile, sqlite3
from datetime import datetime, date
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Python 3.12 deprecated the default sqlite3 datetime adapters.
# Register explicit ISO adapters so sqlite I/O doesn't warn.
sqlite3.register_adapter(date, date.isoformat)
sqlite3.register_adapter(datetime, datetime.isoformat)

from threading import Lock
from contextlib import contextmanager
from pave.metadb import CollectionDB
from pave.stores.base import BaseStore, Record, SearchResult
from pave.backends import FaissBackend, VectorBackend
from pave.embedders import get_embedder
from pave.config import CFG as c, get_logger

log = get_logger()

_LOCKS: dict[str, Lock] = {}
_LOCKS_GUARD = Lock()  # Protects _LOCKS dictionary creation
_SQL_TRANS = str.maketrans({
    ";": " ",
    '"': " ",
    "`": " ",
    "\\": " ",
    "\x00": "",
})

def get_lock(key: str) -> Lock:
    """Get or create a lock for a given key, thread-safe."""
    if key not in _LOCKS:
        with _LOCKS_GUARD:
            if key not in _LOCKS:  # double-check after acquiring guard
                _LOCKS[key] = Lock()
    return _LOCKS[key]

@contextmanager
def collection_lock(tenant: str, collection: str):
    lock = get_lock(f"t_{tenant}:c_{collection}")
    lock.acquire()
    try:
        yield
    finally:
        lock.release()

class FaissStore(BaseStore):
    # Maximum depth for recursive collection traversal in filter matching
    _FILTER_MATCH_MAX_DEPTH = 10

    def __init__(self):
        self._emb: dict[tuple[str, str], VectorBackend] = {}
        self._dbs: dict[tuple[str, str], CollectionDB] = {}
        self._embedder = get_embedder()

    def _base_path(self, tenant: str, collection: str) -> str:
        return os.path.join(c.get("data_dir"), f"t_{tenant}", f"c_{collection}")

    def _db_path(self, tenant: str, collection: str) -> Path:
        return Path(self._base_path(tenant, collection)) / "meta.db"

    def _load_json(self, path: str):
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
            except Exception:
                return {}
        return {}

    def _save_json(self, path: str, data):
        d = os.path.dirname(path)
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def load_or_init(self, tenant: str, collection: str) -> None:
        key = (tenant, collection)
        if key in self._emb:
            return

        base = self._base_path(tenant, collection)
        os.makedirs(base, exist_ok=True)

        idx_dir = Path(os.path.join(base, "index"))
        backend = FaissBackend(
            self._embedder.dim,
            storage_dir=idx_dir,
        )

        try:
            backend.initialize()
        except Exception:
            log.warning(
                "Corrupt index at %s for %s/%s, starting fresh",
                idx_dir,
                tenant,
                collection,
            )
            backend = FaissBackend(
                self._embedder.dim,
                storage_dir=idx_dir,
            )

        self._emb[key] = backend

        # Open CollectionDB if not already open
        if key not in self._dbs:
            col_db = CollectionDB()
            col_db.open(self._db_path(tenant, collection))
            self._dbs[key] = col_db

    def save(self, tenant: str, collection: str) -> None:
        key = (tenant, collection)
        em = self._emb.get(key)
        if not em:
            return
        em.flush()

    def delete_collection(self, tenant: str, collection: str) -> None:
        import shutil
        with collection_lock(tenant, collection):
            key = (tenant, collection)
            backend = self._emb.pop(key, None)
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass
            col_db = self._dbs.pop(key, None)
            if col_db is not None:
                col_db.close()
            p = self._base_path(tenant, collection)
            if os.path.isdir(p):
                shutil.rmtree(p)

    def rename_collection(self, tenant: str, old_name: str, new_name: str) -> None:
        if old_name == new_name:
            raise ValueError(
                f"old and new collection names are the same: {old_name}"
            )

        old_key = (tenant, old_name)
        new_key = (tenant, new_name)
        old_path = self._base_path(tenant, old_name)
        new_path = self._base_path(tenant, new_name)

        # Acquire locks in sorted order to prevent deadlock
        lock_old = get_lock(f"t_{tenant}:c_{old_name}")
        lock_new = get_lock(f"t_{tenant}:c_{new_name}")
        locks = sorted([lock_old, lock_new], key=id)
        locks[0].acquire()
        locks[1].acquire()
        try:
            # Pre-checks
            if not os.path.isdir(old_path):
                raise ValueError(f"collection '{old_name}' does not exist")
            if os.path.exists(new_path):
                raise ValueError(f"collection '{new_name}' already exists")

            # Close DB for old collection before rename
            old_db = self._dbs.pop(old_key, None)
            if old_db is not None:
                old_db.close()

            # Atomic directory rename
            os.rename(old_path, new_path)

            # Update in-memory cache for vector backends
            if old_key in self._emb:
                self._emb[new_key] = self._emb.pop(old_key)

            # Re-open CollectionDB at new path
            col_db = CollectionDB()
            col_db.open(self._db_path(tenant, new_name))
            self._dbs[new_key] = col_db
        finally:
            locks[1].release()
            locks[0].release()

    @staticmethod
    def _is_transient_db_read_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        if isinstance(exc, sqlite3.ProgrammingError):
            return "closed database" in msg
        if isinstance(exc, sqlite3.OperationalError):
            return (
                "unable to open database file" in msg
                or "database is locked" in msg
            )
        if isinstance(exc, RuntimeError):
            return (
                "not opened" in msg
                or "closing" in msg
                or "closed" in msg
            )
        return False

    def _read_meta_batch_safe(
        self, tenant: str, collection: str, rids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not rids:
            return {}

        key = (tenant, collection)
        cached = self._dbs.get(key)
        if cached is not None:
            try:
                return cached.get_meta_batch(rids)
            except Exception as e:
                if not self._is_transient_db_read_error(e):
                    raise
                log.debug(
                    "Transient cached meta read failure for %s/%s: %s",
                    tenant, collection, e,
                )

        db_path = self._db_path(tenant, collection)
        if not db_path.exists():
            return {}

        fallback = CollectionDB()
        try:
            fallback.open(db_path, read_only=True)
            return fallback.get_meta_batch(rids)
        except Exception as e:
            if not self._is_transient_db_read_error(e):
                raise
            log.debug(
                "Transient fallback meta read failure for %s/%s: %s",
                tenant, collection, e,
            )
            return {}
        finally:
            try:
                fallback.close()
            except Exception:
                pass

    def list_collections(self, tenant: str) -> list[str]:
        tenant_path = os.path.join(c.get("data_dir"), f"t_{tenant}")
        if not os.path.isdir(tenant_path):
            return []
        collections: list[str] = []
        for entry in os.listdir(tenant_path):
            if not entry.startswith("c_"):
                continue
            collection = entry[2:]
            if not collection:
                continue
            coll_dir = os.path.join(tenant_path, entry)
            if os.path.isfile(os.path.join(coll_dir, "meta.db")):
                collections.append(collection)
        return collections

    def list_tenants(self, data_dir: str) -> list[str]:
        from pathlib import Path
        data_dir_path = Path(data_dir).resolve()
        if not data_dir_path.is_dir():
            return []
        tenants: list[str] = []
        for entry in data_dir_path.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            if not name.startswith("t_"):
                continue
            tenant = name[2:]
            if tenant:
                tenants.append(tenant)
        return tenants

    def catalog_metrics(self, data_dir: str) -> dict[str, int]:
        """Return tenant/collection/doc/chunk counters from store metadata."""
        from pathlib import Path

        data_dir_path = Path(data_dir).resolve()
        if not data_dir_path.is_dir():
            return {
                "tenant_count": 0,
                "collection_count": 0,
                "doc_count": 0,
                "chunk_count": 0,
            }

        tenants: set[str] = set()
        collection_count = 0
        doc_count = 0
        chunk_count = 0

        for tenant_dir in data_dir_path.iterdir():
            if not tenant_dir.is_dir():
                continue
            tname = tenant_dir.name
            if not tname.startswith("t_"):
                continue
            tenant = tname[2:]
            if not tenant:
                continue
            tenants.add(tenant)

            for coll_dir in tenant_dir.iterdir():
                if not coll_dir.is_dir():
                    continue
                cname = coll_dir.name
                if not cname.startswith("c_"):
                    continue
                collection = cname[2:]
                if not collection:
                    continue

                db_path = coll_dir / "meta.db"
                if not db_path.is_file():
                    continue

                collection_count += 1
                key = (tenant, collection)

                col_db = self._dbs.get(key)
                close_after = False
                if col_db is None:
                    col_db = CollectionDB()
                    col_db.open(db_path, read_only=True)
                    close_after = True
                try:
                    docs, chunks = col_db.get_doc_chunk_counts()
                    doc_count += docs
                    chunk_count += chunks
                finally:
                    if close_after:
                        col_db.close()

        return {
            "tenant_count": len(tenants),
            "collection_count": collection_count,
            "doc_count": doc_count,
            "chunk_count": chunk_count,
        }

    def has_doc(self, tenant: str, collection: str, docid: str) -> bool:
        key = (tenant, collection)
        col_db = self._dbs.get(key)
        if col_db is not None:
            try:
                return col_db.has_doc(docid)
            except Exception as e:
                if not self._is_transient_db_read_error(e):
                    raise
        # Fallback: open DB read-only (no wconn, no migrations)
        db_path = self._db_path(tenant, collection)
        if not db_path.exists():
            return False
        col_db = CollectionDB()
        try:
            col_db.open(db_path, read_only=True)
            return col_db.has_doc(docid)
        except Exception as e:
            if self._is_transient_db_read_error(e):
                return False
            raise
        finally:
            try:
                col_db.close()
            except Exception:
                pass

    def purge_doc(self, tenant: str, collection: str, docid: str) -> int:
        with collection_lock(tenant, collection):
            self.load_or_init(tenant, collection)
            key = (tenant, collection)
            col_db = self._dbs[key]
            ids = col_db.get_rids_for_doc(docid)
            if not ids:
                return 0

            # remove sidecar .txt files
            for urid in ids:
                p = os.path.join(
                    self._chunks_dir(tenant, collection),
                    self._urid_to_fname(urid)
                )
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

            # delete from SQLite (chunks + documents rows)
            col_db.delete_doc(docid)

            # delete vectors for these chunk ids
            backend = self._emb.get(key)
            if backend and ids:
                try:
                    backend.delete(ids)
                except Exception:
                    # Skip silently. Metadata-side cleanup already happened
                    # and searches hydrate text from sidecars.
                    pass

            self.save(tenant, collection)
            return len(ids)

    def _chunks_dir(self, tenant: str, collection: str) -> str:
        return os.path.join(self._base_path(tenant, collection), "chunks")

    def _urid_to_fname(self, urid: str) -> str:
        return (
            urid.replace("/", "_").replace("\\", "_").replace(":", "_") + ".txt"
        )

    def _load_meta(
        self, tenant: str, collection: str
    ) -> dict[str, dict[str, Any]]:
        """Backward-compat helper: load all merged metadata from CollectionDB.

        Returns a dict keyed by rid. Retained so existing tests that
        access this method continue to work after JSON files were replaced
        by SQLite.
        """
        key = (tenant, collection)
        col_db = self._dbs.get(key)
        if col_db is None:
            return {}
        conn = col_db._conn
        if conn is None:
            return {}
        cur = conn.execute("SELECT rid FROM chunks")
        rids = [rid for rid, in cur.fetchall()]
        return col_db.get_meta_batch(rids)

    def _save_chunk_text(self, tenant: str, collection: str,
                         urid: str, t: str) -> None:
        p = os.path.join(self._chunks_dir(tenant, collection),
                         self._urid_to_fname(urid))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = (t or "").encode("utf-8")
        with open(p, "wb") as f:
            f.write(data)
            f.flush()

    def _load_chunk_text(self, tenant: str, collection: str,
                         urid: str) -> str | None:
        p = os.path.join(self._chunks_dir(tenant, collection),
                         self._urid_to_fname(urid))
        if not os.path.isfile(p):
            return None
        try:
            with open(p, "rb") as f:
                return f.read().decode("utf-8")
        except FileNotFoundError:
            # TOCTOU: file was removed between isfile() and open().
            return None
        except OSError:
            return None

    def index_records(self, tenant: str, collection: str, docid: str,
                      records: Iterable[Record],
                      doc_meta: dict[str, Any] | None = None
                      ) -> int:
        """
        Ingests records as (rid, text, meta). Guarantees non-null text, coerces
        dict-records, updates SQLite metadata, saves index. Thread critical.
        """
        with collection_lock(tenant, collection):
            self.load_or_init(tenant, collection)
            key = (tenant, collection)
            col_db = self._dbs[key]
            backend = self._emb[key]
            raw_doc_meta = dict(doc_meta or {})
            raw_doc_meta.setdefault("docid", docid)
            try:
                safe_doc_meta = self._sanit_meta_dict(raw_doc_meta)
            except Exception:
                safe_doc_meta = {"docid": docid}
            rids_to_add: list[str] = []
            texts_to_encode: list[str] = []
            chunk_rows: list[tuple[str, str | None, dict[str, Any]]] = []

            for r in records:
                if isinstance(r, dict):
                    rid = r.get("rid") or r.get("id") or r.get("uid")
                    txt = r.get("text") or r.get("content")
                    md = (
                        r.get("meta") or r.get("metadata") or
                        r.get("tags") or {}
                    )
                else:
                    try:
                        rid, txt, md = r
                    except Exception:
                        continue

                if not rid or txt is None:
                    continue

                if not isinstance(md, dict):
                    if isinstance(md, str):
                        try:
                            md = json.loads(md)
                        except:
                            md = {}
                    else:
                        try:
                            md = dict(md)
                        except:
                            md = {}

                try:
                    safe_meta = self._sanit_meta_dict(md)
                except Exception:
                    safe_meta = {}

                rid = str(rid)
                txt = str(txt)
                if not rid.startswith(f"{docid}::"):
                    rid = f"{docid}::{rid}"

                chunk_path = os.path.join(
                    "chunks", self._urid_to_fname(rid)
                )
                chunk_rows.append((rid, chunk_path, safe_meta))
                rids_to_add.append(rid)
                texts_to_encode.append(txt)

                self._save_chunk_text(tenant, collection, rid, txt)
                loaded = self._load_chunk_text(tenant, collection, rid) or ""
                if txt != loaded:
                    log.warning(
                        f"Chunk text round-trip mismatch for {rid}: "
                        f"saved {len(txt)} chars, loaded {len(loaded)} chars"
                    )

            if not rids_to_add:
                return 0

            # Write metadata to SQLite (inside collection_lock)
            col_db.upsert_chunks(docid, chunk_rows, doc_meta=safe_doc_meta)
            vectors = self._embedder.encode(texts_to_encode)
            backend.add(rids_to_add, vectors)
            self.save(tenant, collection)
            _rids = rids_to_add[:3]
            _sfx = " ..." if len(rids_to_add) > 3 else ""
            log.debug(
                f"INGEST-PREPARED: {len(rids_to_add)} chunks {_rids}{_sfx}"
            )
            return len(rids_to_add)

    @staticmethod
    def _matches_filters(m: dict[str, Any],
                         filters: dict[str, Any] | None) -> bool:
        """
        Evaluates whether metadata `m` satisfies all filter conditions.
        Supports:
          - wildcards (*xyz / xyz*)
          - numeric comparisons (>, <, >=, <=, !=)
          - datetime comparisons (ISO 8601)
        Multiple values in the same key act as OR; multiple keys act as AND.
        """
        if not filters:
            return True

        def match(have: Any, cond: Any, depth: int = 0) -> bool:
            # Prevent infinite recursion with deeply nested collections
            if depth >= FaissStore._FILTER_MATCH_MAX_DEPTH:
                log.warning(
                    f"Filter match depth limit "
                    f"({FaissStore._FILTER_MATCH_MAX_DEPTH}) "
                    f"exceeded for value: {type(have)}"
                )
                return False

            if have is None:
                return False
            if isinstance(have, (list, tuple, set)):
                return any(match(item, cond, depth + 1) for item in have)
            if isinstance(cond, str):
                s = FaissStore._sanit_sql(cond)
            else:
                s = str(cond)
            hv = str(have)
            # Numeric/date ops
            _OPS = {">=": operator.ge, "<=": operator.le,
                    "!=": operator.ne,
                    ">": operator.gt, "<": operator.lt}
            for op_str, op_fn in _OPS.items():
                if s.startswith(op_str):
                    val = s[len(op_str):].strip()
                    try:
                        hvn, vvn = float(have), float(val)
                        return op_fn(hvn, vvn)
                    except Exception:
                        try:
                            hd = datetime.fromisoformat(str(have))
                            vd = datetime.fromisoformat(val)
                            return op_fn(hd, vd)
                        except Exception:
                            return False
            # Wildcards
            if s == "*":
                return True
            if s.startswith("*") and s.endswith("*") and s[1:-1] in hv:
                return True
            if s.startswith("*") and hv.endswith(s[1:]):
                return True
            if s.endswith("*") and hv.startswith(s[:-1]):
                return True
            if s.startswith("!") and len(s) > 1:
                return hv != s[1:]
            return hv == s

        for k, vals in filters.items():
            if not any(
                match(FaissStore._lookup_meta(m, k), v) for v in vals
            ):
                return False
        return True

    @staticmethod
    def _lookup_meta(meta: dict[str, Any] | None, key: str) -> Any:
        if not meta:
            return None
        if key in meta:
            return meta.get(key)
        for raw_key, value in meta.items():
            if FaissStore._sanit_field(raw_key) == key:
                return value
        return None

    @staticmethod
    def _sanit_meta_value(value: Any) -> Any:
        if isinstance(value, dict):
            return FaissStore._sanit_meta_dict(value)
        if isinstance(value, (list, tuple, set)):
            return [FaissStore._sanit_meta_value(v) for v in value]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return FaissStore._sanit_sql(value)

    @staticmethod
    def _sanit_meta_dict(meta: dict[str, Any] | None) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        if not isinstance(meta, dict):
            return safe
        for raw_key, raw_value in meta.items():
            safe_key = FaissStore._sanit_field(raw_key)
            if not safe_key or safe_key == "text":
                continue
            safe[safe_key] = FaissStore._sanit_meta_value(raw_value)
        return safe

    @staticmethod
    def _sanit_sql(value: Any, *, max_len: int | None = None) -> str:
        if value is None:
            return ""
        text = str(value).translate(_SQL_TRANS)
        for token in ("--", "/*", "*/"):
            if token in text:
                text = text.split(token, 1)[0]
        text = text.strip()
        if max_len is not None and max_len > 0 and len(text) > max_len:
            text = text[:max_len]
        return text.replace("'", "''")

    @staticmethod
    def _sanit_field(name: Any) -> str:
        if not isinstance(name, str):
            name = str(name)
        safe = []
        for ch in name:
            if ch.isalnum() or ch in {"_", "-"}:
                safe.append(ch)
        return "".join(safe)

    def search(self, tenant: str, collection: str, query: str, k: int = 5,
               filters: dict[str, Any] | None = None) -> list[SearchResult]:
        """
        Queries the FAISS backend for top-k and keeps overfetch inside the
        store.

        Key concurrency improvement (Phase 1):
        - FAISS search runs inside collection_lock
        - Meta read (get_meta_batch) runs OUTSIDE lock — WAL concurrent reads
        """
        kk = max(1, int(k))

        fetch_k = max(50, kk * 5)
        normed_filters: dict[str, list[Any]] = {}
        for key, vals in (filters or {}).items():
            safe_key = self._sanit_field(key)
            if not safe_key:
                continue
            if isinstance(vals, list):
                normed_filters[safe_key] = vals
            else:
                normed_filters[safe_key] = [vals]

        with collection_lock(tenant, collection):
            self.load_or_init(tenant, collection)
            key = (tenant, collection)
            backend = self._emb[key]
            col_db = self._dbs.get(key)
            q_vec = self._embedder.encode([query])[0]
            raw = backend.search(q_vec, fetch_k)
            candidate_rids = [rid for rid, _ in raw if rid]

        if normed_filters and col_db is not None:
            surviving = col_db.filter_by_meta(
                candidate_rids,
                normed_filters,
            )
            raw = [(rid, score) for rid, score in raw if rid in surviving]
            candidate_rids = [rid for rid, _score in raw if rid]

        # --- OUTSIDE lock: WAL meta read is concurrent ---
        meta_batch = self._read_meta_batch_safe(tenant, collection, candidate_rids)

        kept: list[tuple[str, float]] = []
        if normed_filters:
            log.debug(f"SEARCH-FILTER-POST: {normed_filters}")
        for rid, score in raw:
            if not rid:
                continue
            rid_meta = meta_batch.get(rid, {})
            if self._matches_filters(rid_meta, normed_filters):
                kept.append((rid, score))
                if len(kept) >= kk:
                    break

        out: list[SearchResult] = []
        for rid, score in kept:
            txt = self._load_chunk_text(tenant, collection, rid)
            rid_meta = meta_batch.get(rid, {})
            out.append(SearchResult(
                id=rid,
                score=score,
                text=txt,
                tenant=tenant,
                collection=collection,
                meta=rid_meta,
                match_reason=self._build_match_reason(
                    query, score, filters, rid_meta
                ),
            ))
        _hits = [(r.id, round(r.score, 3)) for r in out[:3]]
        _sfx = " ..." if len(out) > 3 else ""
        log.debug(f"SEARCH-OUT: {len(out)} hits {_hits}{_sfx}")
        return out

    def _build_match_reason(self, query: str, score: float,
                            filters: dict[str, Any] | None,
                            meta: dict[str, Any] | None) -> str:
        """Build a human-readable explanation of why a result matched."""
        parts = []

        # Similarity component
        pct = int(score * 100)
        if query:
            parts.append(f"semantic similarity {pct}%")

        # Filter matches - show which filter conditions were satisfied
        if filters:
            filter_parts = []
            for key, vals in filters.items():
                meta_val = self._lookup_meta(meta, key)
                if meta_val is not None:
                    # Show the actual value that matched
                    filter_parts.append(f"{key}={meta_val}")
            if filter_parts:
                parts.append("filters: " + ", ".join(filter_parts))

        return "; ".join(parts) if parts else "matched"
