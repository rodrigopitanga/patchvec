# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pave.meta_store import CollectionDB, LegacyMetadataError


def _meta_db(tmp_path: Path) -> Path:
    return tmp_path / "t_acme" / "c_demo" / "meta.db"


def test_open_creates_schema(tmp_path):
    db_path = _meta_db(tmp_path)
    db = CollectionDB()
    db.open(db_path)
    conn = db._conn
    assert conn is not None
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('schema_migrations', 'documents', 'chunks')"
    )
    names = {row[0] for row in cur.fetchall()}
    assert {"schema_migrations", "documents", "chunks"} <= names
    db.close()


@pytest.mark.parametrize("legacy_name", ["catalog.json", "meta.json"])
def test_legacy_json_detection(tmp_path, legacy_name):
    base = _meta_db(tmp_path).parent
    base.mkdir(parents=True, exist_ok=True)
    (base / legacy_name).write_text("{}", encoding="utf-8")
    db = CollectionDB()
    with pytest.raises(LegacyMetadataError):
        db.open(base / "meta.db")


def test_upsert_and_get_meta(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    chunks = [
        ("doc1::c0", "chunks/doc1::c0.txt", {"docid": "doc1", "chunk": 0}),
        ("doc1::c1", "chunks/doc1::c1.txt", {"docid": "doc1", "chunk": 1}),
    ]
    db.upsert_chunks("doc1", chunks, doc_meta={"docid": "doc1"})
    assert db.has_doc("doc1") is True
    rids = db.get_rids_for_doc("doc1")
    assert set(rids) == {"doc1::c0", "doc1::c1"}
    meta = db.get_meta_batch(rids)
    assert meta["doc1::c0"]["chunk"] == 0
    assert meta["doc1::c1"]["chunk"] == 1
    assert db.get_doc_version("doc1") == 1
    db.close()


def test_delete_doc(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    chunks = [
        ("doc2::c0", "chunks/doc2::c0.txt", {"docid": "doc2"}),
    ]
    db.upsert_chunks("doc2", chunks, doc_meta={"docid": "doc2"})
    deleted = db.delete_doc("doc2")
    assert deleted == ["doc2::c0"]
    assert db.has_doc("doc2") is False
    db.close()


def test_get_doc_chunk_counts(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc3",
        [
            ("doc3::c0", "chunks/doc3::c0.txt", {"docid": "doc3"}),
            ("doc3::c1", "chunks/doc3::c1.txt", {"docid": "doc3"}),
        ],
        doc_meta={"docid": "doc3"},
    )
    db.upsert_chunks(
        "doc4",
        [("doc4::c0", "chunks/doc4::c0.txt", {"docid": "doc4"})],
        doc_meta={"docid": "doc4"},
    )
    assert db.get_doc_chunk_counts() == (2, 3)
    db.close()
