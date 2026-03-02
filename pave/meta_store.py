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
from datetime import datetime, timezone as tz
from pathlib import Path
from typing import Any


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

    def _open_conn(self, path: Path) -> sqlite3.Connection:
        """Open a single sqlite3 connection with standard pragmas."""
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def open(self, path: Path) -> None:
        """Open (or create) the meta.db at *path*.

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
        parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._rconn = self._open_conn(path)
        self._wconn = self._open_conn(path)
        self._apply_migrations()

    def close(self) -> None:
        if self._rconn is not None:
            self._rconn.close()
            self._rconn = None
        if self._wconn is not None:
            self._wconn.close()
            self._wconn = None

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

    def delete_doc(self, docid: str) -> list[str]:
        """Delete all chunks and the document row for *docid*.

        Returns the list of rids that were deleted.
        Must be called inside collection_lock.
        """
        # Read rids using _rconn (no lock needed)
        rconn = self._require_rconn()
        cur = rconn.execute(
            "SELECT rid FROM chunks WHERE docid=?", (docid,)
        )
        rids = [row[0] for row in cur.fetchall()]
        # Write using _wconn
        conn = self._require_wconn()
        with self._write_lock, conn:
            conn.execute("DELETE FROM chunks WHERE docid=?", (docid,))
            conn.execute("DELETE FROM documents WHERE docid=?", (docid,))
        return rids

    # ------------------------------------------------------------------
    # Read operations — use _rconn, no lock needed (WAL)
    # ------------------------------------------------------------------

    def has_doc(self, docid: str) -> bool:
        """Return True if *docid* has at least one chunk row."""
        conn = self._require_rconn()
        cur = conn.execute(
            "SELECT 1 FROM chunks WHERE docid=? LIMIT 1", (docid,)
        )
        return cur.fetchone() is not None

    def get_rids_for_doc(self, docid: str) -> list[str]:
        conn = self._require_rconn()
        cur = conn.execute(
            "SELECT rid FROM chunks WHERE docid=?", (docid,)
        )
        return [row[0] for row in cur.fetchall()]

    def get_doc_version(self, docid: str) -> int | None:
        conn = self._require_rconn()
        cur = conn.execute(
            "SELECT version FROM documents WHERE docid=?", (docid,)
        )
        row = cur.fetchone()
        return int(row[0]) if row else None

    def get_meta_batch(self, rids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch per-chunk metadata for *rids*.

        Called OUTSIDE collection_lock — WAL reads via _rconn are concurrent.
        Chunks the rid list into groups of 999 (SQLite variable limit).
        """
        if not rids:
            return {}
        conn = self._require_rconn()
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
