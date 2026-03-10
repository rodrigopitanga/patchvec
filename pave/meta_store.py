# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
CollectionDB — impl2: read/write split connections.

Two persistent connections (check_same_thread=False):
  _rconn: read connection (WAL, no lock, concurrent reads)
  _wconn: write connection (serialised by _write_lock)
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone as tz
from pathlib import Path
from typing import Any, Iterator


class LegacyMetadataError(RuntimeError):
    pass


_MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS documents (
            docid       TEXT PRIMARY KEY,
            version     INTEGER NOT NULL DEFAULT 1,
            ingested_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            ),
            meta_json   TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS chunks (
            docid       TEXT NOT NULL,
            rid         TEXT PRIMARY KEY,
            chunk_path  TEXT,
            meta_json   TEXT NOT NULL DEFAULT '{}',
            ingested_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            )
        )
        """,
        "CREATE INDEX IF NOT EXISTS chunks_docid ON chunks (docid)",
    ],
    2: [
        """
        CREATE TABLE IF NOT EXISTS chunk_meta (
            rid   TEXT NOT NULL,
            key   TEXT NOT NULL,
            value TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS chunk_meta_rid
            ON chunk_meta (rid)
        """,
        """
        CREATE INDEX IF NOT EXISTS chunk_meta_kv
            ON chunk_meta (key, value)
        """,
    ],
}


class CollectionDB:
    """Per-collection SQLite metadata store (impl2).

    Two persistent connections with check_same_thread=False:
      _rconn: used for all reads (WAL, no lock, fully concurrent)
      _wconn: used for all writes (protected by _write_lock)
    """

    def __init__(self) -> None:
        self.path: Path | None = None
        self._rconn: sqlite3.Connection | None = None
        self._wconn: sqlite3.Connection | None = None
        self._write_lock = threading.Lock()
        self._state_cv = threading.Condition()
        self._active_readers = 0
        self._closing = False

    def _open_conn(self, path: Path) -> sqlite3.Connection:
        """Open a single sqlite3 connection with standard pragmas."""
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def open(self, path: Path, *, read_only: bool = False) -> None:
        """Open (or create) the meta.db at *path*.

        When *read_only* is True only the read connection is opened
        and migrations are skipped.  Use this for fallback reads
        (``has_doc``, ``catalog_metrics``, ``_read_meta_batch_safe``)
        where a write connection is unnecessary.

        Raises LegacyMetadataError if catalog.json or meta.json exist
        alongside the database file.
        """
        path = path.resolve()
        parent = path.parent
        if parent.exists():
            if ((parent / "catalog.json").exists()
                    or (parent / "meta.json").exists()):
                raise LegacyMetadataError(
                    f"Legacy catalog.json/meta.json detected in {parent}; "
                    "migration not supported — remove JSON files first."
                )
        if not read_only:
            parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._state_cv:
            self._rconn = self._open_conn(path)
            if not read_only:
                self._wconn = self._open_conn(path)
            self._active_readers = 0
            self._closing = False
        if not read_only:
            self._apply_migrations()

    def close(self) -> None:
        with self._state_cv:
            if self._rconn is None and self._wconn is None:
                self._closing = False
                return
            self._closing = True
            while self._active_readers > 0:
                self._state_cv.wait(timeout=0.05)
            rconn = self._rconn
            wconn = self._wconn
            self._rconn = None
            self._wconn = None
            self._closing = False

        if rconn is not None:
            rconn.close()
        if wconn is not None:
            wconn.close()

    @property
    def _conn(self) -> sqlite3.Connection | None:
        """Return read connection (for test introspection)."""
        return self._rconn

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_rconn(self) -> sqlite3.Connection:
        if self._rconn is None:
            raise RuntimeError("CollectionDB not opened; call open() first.")
        return self._rconn

    def _require_wconn(self) -> sqlite3.Connection:
        if self._wconn is None:
            raise RuntimeError("CollectionDB not opened; call open() first.")
        return self._wconn

    @contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        with self._state_cv:
            if self._rconn is None:
                raise RuntimeError("CollectionDB not opened; call open() first.")
            if self._closing:
                raise RuntimeError("CollectionDB is closing.")
            self._active_readers += 1
            conn = self._rconn
        try:
            yield conn
        finally:
            with self._state_cv:
                if self._active_readers > 0:
                    self._active_readers -= 1
                if self._closing and self._active_readers == 0:
                    self._state_cv.notify_all()

    def _apply_migrations(self) -> None:
        conn = self._require_wconn()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        cur = conn.execute("SELECT MAX(version) FROM schema_migrations")
        row = cur.fetchone()
        current = int(row[0] or 0)
        for version in sorted(_MIGRATIONS):
            if version <= current:
                continue
            for stmt in _MIGRATIONS[version]:
                conn.execute(stmt)
            now = datetime.now(tz.utc).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) "
                "VALUES (?, ?)",
                (version, now),
            )
        conn.commit()

    # ------------------------------------------------------------------
    # Write operations — serialised by _write_lock, use _wconn
    # ------------------------------------------------------------------

    def upsert_chunks(
        self,
        docid: str,
        chunks: list[tuple[str, str | None, dict[str, Any]]],
        doc_meta: dict[str, Any] | None = None,
    ) -> None:
        """Insert/replace chunk rows and upsert the document row.

        All writes happen in a single transaction.
        Must be called inside collection_lock.
        """
        conn = self._require_wconn()
        doc_meta_json = json.dumps(doc_meta or {}, ensure_ascii=False)
        now = datetime.now(tz.utc).isoformat(timespec="seconds")
        rows = []
        for rid, chunk_path, meta in chunks:
            meta_json = json.dumps(meta, ensure_ascii=False)
            rows.append((docid, rid, chunk_path, meta_json, now))
        with self._write_lock, conn:
            conn.execute(
                """
                INSERT INTO documents (docid, version, ingested_at, meta_json)
                VALUES (
                    ?,
                    COALESCE(
                        (SELECT version FROM documents WHERE docid=?), 0
                    ) + 1,
                    ?,
                    ?
                )
                ON CONFLICT(docid) DO UPDATE SET
                    version=excluded.version,
                    ingested_at=excluded.ingested_at,
                    meta_json=excluded.meta_json
                """,
                (docid, docid, now, doc_meta_json),
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO chunks
                (docid, rid, chunk_path, meta_json, ingested_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            if chunks:
                rids = [rid for rid, _chunk_path, _meta in chunks]
                for i in range(0, len(rids), 999):
                    batch = rids[i : i + 999]
                    placeholders = ",".join(["?"] * len(batch))
                    conn.execute(
                        f"DELETE FROM chunk_meta "
                        f"WHERE rid IN ({placeholders})",
                        batch,
                    )
            kv_rows: list[tuple[str, str, str]] = []
            for rid, _chunk_path, meta in chunks:
                for mk, mv in meta.items():
                    kv_rows.append((rid, str(mk), str(mv)))
            if kv_rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO chunk_meta "
                    "(rid, key, value) VALUES (?, ?, ?)",
                    kv_rows,
                )

    def delete_doc(self, docid: str) -> list[str]:
        """Delete all chunks and the document row for *docid*.

        Returns the list of rids that were deleted.
        Must be called inside collection_lock.
        """
        # Read rids using _rconn (no lock needed)
        with self._reader() as rconn:
            cur = rconn.execute(
                "SELECT rid FROM chunks WHERE docid=?", (docid,)
            )
            rids = [row[0] for row in cur.fetchall()]
        # Write using _wconn
        conn = self._require_wconn()
        with self._write_lock, conn:
            if rids:
                for i in range(0, len(rids), 999):
                    batch = rids[i : i + 999]
                    placeholders = ",".join(["?"] * len(batch))
                    conn.execute(
                        f"DELETE FROM chunk_meta "
                        f"WHERE rid IN ({placeholders})",
                        batch,
                    )
            conn.execute("DELETE FROM chunks WHERE docid=?", (docid,))
            conn.execute("DELETE FROM documents WHERE docid=?", (docid,))
        return rids

    # ------------------------------------------------------------------
    # Read operations — use _rconn, no lock needed (WAL)
    # ------------------------------------------------------------------

    def has_doc(self, docid: str) -> bool:
        """Return True if *docid* has at least one chunk row."""
        with self._reader() as conn:
            cur = conn.execute(
                "SELECT 1 FROM chunks WHERE docid=? LIMIT 1", (docid,)
            )
            return cur.fetchone() is not None

    def get_rids_for_doc(self, docid: str) -> list[str]:
        with self._reader() as conn:
            cur = conn.execute(
                "SELECT rid FROM chunks WHERE docid=?", (docid,)
            )
            return [row[0] for row in cur.fetchall()]

    def get_doc_version(self, docid: str) -> int | None:
        with self._reader() as conn:
            cur = conn.execute(
                "SELECT version FROM documents WHERE docid=?", (docid,)
            )
            row = cur.fetchone()
            return int(row[0]) if row else None

    def get_doc_chunk_counts(self) -> tuple[int, int]:
        """Return (doc_count, chunk_count) for this collection."""
        with self._reader() as conn:
            cur = conn.execute(
                "SELECT COUNT(DISTINCT docid), COUNT(*) FROM chunks"
            )
            row = cur.fetchone()
            if row is None:
                return (0, 0)
            return (int(row[0] or 0), int(row[1] or 0))

    def _chunk_meta_matches(
        self,
        conn: sqlite3.Connection,
        candidate_rids: list[str],
        key: str,
        value: str,
    ) -> set[str]:
        matches: set[str] = set()
        for i in range(0, len(candidate_rids), 999):
            batch = candidate_rids[i : i + 999]
            placeholders = ",".join(["?"] * len(batch))
            cur = conn.execute(
                f"SELECT rid FROM chunk_meta "
                f"WHERE key=? AND value=? "
                f"AND rid IN ({placeholders})",
                [key, value, *batch],
            )
            matches.update(row[0] for row in cur.fetchall())
        return matches

    def filter_by_meta(
        self,
        candidate_rids: list[str],
        filters: dict[str, list[str]],
    ) -> set[str]:
        """Reduce candidates via SQL on chunk_meta.

        Handles exact-match and negation (!value) only.
        Values with *, >, <, >=, <= are skipped (left for
        caller's canonical post-filter).
        Returns subset of candidate_rids passing all
        pushdown-able conditions.
        """
        if not candidate_rids:
            return set()
        if not filters:
            return set(candidate_rids)

        current = set(candidate_rids)
        skip_prefixes = (">=", "<=", "!=", ">", "<")

        with self._reader() as conn:
            for key, values in filters.items():
                if not current:
                    break

                current_batch = list(current)
                key_matches: set[str] = set()
                saw_pushdown = False

                for raw_value in values:
                    if not isinstance(raw_value, str):
                        continue
                    if "*" in raw_value:
                        continue
                    if raw_value.startswith(skip_prefixes):
                        continue

                    if raw_value.startswith("!") and len(raw_value) > 1:
                        matched = self._chunk_meta_matches(
                            conn,
                            current_batch,
                            key,
                            raw_value[1:],
                        )
                        key_matches.update(current - matched)
                        saw_pushdown = True
                        continue

                    matched = self._chunk_meta_matches(
                        conn,
                        current_batch,
                        key,
                        raw_value,
                    )
                    key_matches.update(matched)
                    saw_pushdown = True

                if saw_pushdown:
                    current.intersection_update(key_matches)

        return current

    def get_meta_batch(self, rids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch per-chunk metadata for *rids*.

        Called OUTSIDE collection_lock — WAL reads via _rconn are concurrent.
        Chunks the rid list into groups of 999 (SQLite variable limit).
        """
        if not rids:
            return {}
        with self._reader() as conn:
            out: dict[str, dict[str, Any]] = {}
            chunk_size = 999
            for i in range(0, len(rids), chunk_size):
                batch = rids[i : i + chunk_size]
                placeholders = ",".join(["?"] * len(batch))
                cur = conn.execute(
                    f"SELECT rid, meta_json FROM chunks "
                    f"WHERE rid IN ({placeholders})",
                    batch,
                )
                for rid, meta_json in cur.fetchall():
                    try:
                        out[rid] = json.loads(meta_json) if meta_json else {}
                    except Exception:
                        out[rid] = {}
            return out
