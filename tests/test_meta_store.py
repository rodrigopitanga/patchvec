# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pytest

from pave.metadb import CollectionDB, LegacyMetadataError


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
        "AND name IN "
        "('schema_migrations', 'documents', 'chunks', "
        "'chunk_meta', 'document_meta')"
    )
    names = {row[0] for row in cur.fetchall()}
    assert {
        "schema_migrations",
        "documents",
        "chunks",
        "chunk_meta",
        "document_meta",
    } <= names
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
        (
            "doc1::chunk_0",
            "chunks/doc1__chunk_0.txt",
            {"docid": "doc1", "chunk": 0},
        ),
        (
            "doc1::chunk_1",
            "chunks/doc1__chunk_1.txt",
            {"docid": "doc1", "chunk": 1},
        ),
    ]
    db.upsert_chunks("doc1", chunks, doc_meta={"docid": "doc1"})
    assert db.has_doc("doc1") is True
    rids = db.get_rids_for_doc("doc1")
    assert set(rids) == {"doc1::chunk_0", "doc1::chunk_1"}
    meta = db.get_meta_batch(rids)
    assert meta["doc1::chunk_0"]["chunk"] == 0
    assert meta["doc1::chunk_1"]["chunk"] == 1
    assert db.get_doc_version("doc1") == 1
    db.close()


def test_delete_doc(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    chunks = [
        ("doc2::chunk_0", "chunks/doc2__chunk_0.txt", {"docid": "doc2"}),
    ]
    db.upsert_chunks("doc2", chunks, doc_meta={"docid": "doc2"})
    deleted = db.delete_doc("doc2")
    assert deleted == ["doc2::chunk_0"]
    assert db.has_doc("doc2") is False
    db.close()


def test_open_read_only_skips_wconn_and_migrations(tmp_path):
    db_path = _meta_db(tmp_path)
    # First open normally to create schema
    db = CollectionDB()
    db.open(db_path)
    db.upsert_chunks(
        "doc1",
        [("doc1::chunk_0", "chunks/doc1__chunk_0.txt", {"docid": "doc1"})],
        doc_meta={"docid": "doc1"},
    )
    db.close()

    # Re-open read-only
    ro = CollectionDB()
    ro.open(db_path, read_only=True)
    assert ro._rconn is not None
    assert ro._wconn is None
    assert ro.has_doc("doc1") is True
    meta = ro.get_meta_batch(["doc1::chunk_0"])
    assert meta["doc1::chunk_0"]["docid"] == "doc1"
    ro.close()


def test_open_read_only_does_not_create_dirs(tmp_path):
    db_path = tmp_path / "nonexistent" / "sub" / "meta.db"
    db = CollectionDB()
    with pytest.raises(Exception):
        db.open(db_path, read_only=True)
    assert not db_path.parent.exists()


def test_get_doc_chunk_counts(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc3",
        [
            ("doc3::chunk_0", "chunks/doc3__chunk_0.txt", {"docid": "doc3"}),
            ("doc3::chunk_1", "chunks/doc3__chunk_1.txt", {"docid": "doc3"}),
        ],
        doc_meta={"docid": "doc3"},
    )
    db.upsert_chunks(
        "doc4",
        [("doc4::chunk_0", "chunks/doc4__chunk_0.txt", {"docid": "doc4"})],
        doc_meta={"docid": "doc4"},
    )
    assert db.get_doc_chunk_counts() == (2, 3)
    db.close()


def test_chunk_meta_populated_on_upsert(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc1",
        [
            (
                "doc1::chunk_0",
                "chunks/doc1__chunk_0.txt",
                {"docid": "doc1", "lang": "en", "chunk": 0},
            ),
        ],
        doc_meta={"docid": "doc1"},
    )

    conn = db._conn
    assert conn is not None
    rows = conn.execute(
        "SELECT rid, key, value FROM chunk_meta ORDER BY rid, key"
    ).fetchall()

    assert rows == [
        ("doc1::chunk_0", "chunk", "0"),
        ("doc1::chunk_0", "docid", "doc1"),
        ("doc1::chunk_0", "lang", "en"),
    ]
    db.close()


def test_document_meta_populated_on_upsert(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc1",
        [
            (
                "doc1::chunk_0",
                "chunks/doc1__chunk_0.txt",
                {"chunk": 0},
            ),
        ],
        doc_meta={"docid": "doc1", "lang": "en", "source": "api"},
    )

    conn = db._conn
    assert conn is not None
    rows = conn.execute(
        "SELECT docid, key, value FROM document_meta ORDER BY docid, key"
    ).fetchall()

    assert rows == [
        ("doc1", "docid", "doc1"),
        ("doc1", "lang", "en"),
        ("doc1", "source", "api"),
    ]
    db.close()


def test_chunk_meta_cleaned_on_delete(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc1",
        [
            (
                "doc1::chunk_0",
                "chunks/doc1__chunk_0.txt",
                {"docid": "doc1", "lang": "en"},
            ),
        ],
        doc_meta={"docid": "doc1"},
    )

    db.delete_doc("doc1")

    conn = db._conn
    assert conn is not None
    count = conn.execute("SELECT COUNT(*) FROM chunk_meta").fetchone()[0]
    assert count == 0
    doc_count = conn.execute(
        "SELECT COUNT(*) FROM document_meta"
    ).fetchone()[0]
    assert doc_count == 0
    db.close()


def test_chunk_meta_reupsert_replaces_stale_rows(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc1",
        [
            (
                "doc1::chunk_0",
                "chunks/doc1__chunk_0.txt",
                {"docid": "doc1", "lang": "en", "category": "ml"},
            ),
        ],
        doc_meta={"docid": "doc1"},
    )

    db.upsert_chunks(
        "doc1",
        [
            (
                "doc1::chunk_0",
                "chunks/doc1__chunk_0.txt",
                {"docid": "doc1", "lang": "pt"},
            ),
        ],
        doc_meta={"docid": "doc1"},
    )

    conn = db._conn
    assert conn is not None
    rows = conn.execute(
        "SELECT rid, key, value FROM chunk_meta ORDER BY rid, key"
    ).fetchall()

    assert rows == [
        ("doc1::chunk_0", "docid", "doc1"),
        ("doc1::chunk_0", "lang", "pt"),
    ]
    db.close()


def test_filter_by_meta_applies_exact_negation_or_and_semantics(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc1",
        [
            (
                "doc1::chunk_0",
                "chunks/doc1__chunk_0.txt",
                {"docid": "doc1", "lang": "en", "category": "ml"},
            ),
            (
                "doc1::chunk_1",
                "chunks/doc1__chunk_1.txt",
                {"docid": "doc1", "lang": "en", "category": "infra"},
            ),
        ],
        doc_meta={"docid": "doc1"},
    )
    db.upsert_chunks(
        "doc2",
        [
            (
                "doc2::chunk_0",
                "chunks/doc2__chunk_0.txt",
                {"docid": "doc2", "lang": "pt", "category": "ml"},
            ),
            (
                "doc2::chunk_1",
                "chunks/doc2__chunk_1.txt",
                {"docid": "doc2", "lang": "de", "category": "infra"},
            ),
        ],
        doc_meta={"docid": "doc2"},
    )

    matched = db.filter_by_meta(
        [
            "doc1::chunk_0",
            "doc1::chunk_1",
            "doc2::chunk_0",
            "doc2::chunk_1",
        ],
        {
            "lang": ["en", "!pt"],
            "category": ["ml"],
        },
    )

    assert matched == {"doc1::chunk_0"}
    db.close()


def test_filter_by_meta_matches_document_level_fields(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc1",
        [
            (
                "doc1::chunk_0",
                "chunks/doc1__chunk_0.txt",
                {"chunk": 0, "category": "ml"},
            ),
            (
                "doc1::chunk_1",
                "chunks/doc1__chunk_1.txt",
                {"chunk": 1, "category": "infra"},
            ),
        ],
        doc_meta={"docid": "doc1", "lang": "en", "source": "api"},
    )

    matched = db.filter_by_meta(
        ["doc1::chunk_0", "doc1::chunk_1"],
        {"lang": ["en"], "source": ["api"]},
    )

    assert matched == {"doc1::chunk_0", "doc1::chunk_1"}
    db.close()


def test_filter_by_meta_negates_document_level_fields(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc1",
        [
            (
                "doc1::chunk_0",
                "chunks/doc1__chunk_0.txt",
                {"chunk": 0},
            ),
        ],
        doc_meta={"docid": "doc1", "lang": "en"},
    )
    db.upsert_chunks(
        "doc2",
        [
            (
                "doc2::chunk_0",
                "chunks/doc2__chunk_0.txt",
                {"chunk": 0},
            ),
        ],
        doc_meta={"docid": "doc2", "lang": "pt"},
    )

    all_rids = ["doc1::chunk_0", "doc2::chunk_0"]

    matched = db.filter_by_meta(all_rids, {"lang": ["!pt"]})
    assert matched == {"doc1::chunk_0"}

    matched = db.filter_by_meta(all_rids, {"lang": ["!en"]})
    assert matched == {"doc2::chunk_0"}
    db.close()


def test_get_meta_batch_merges_document_and_chunk_metadata(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc1",
        [
            (
                "doc1::chunk_0",
                "chunks/doc1__chunk_0.txt",
                {"chunk": 0, "lang": "pt"},
            ),
        ],
        doc_meta={"docid": "doc1", "filename": "meta.txt", "lang": "en"},
    )

    meta = db.get_meta_batch(["doc1::chunk_0"])

    assert meta == {
        "doc1::chunk_0": {
            "docid": "doc1",
            "filename": "meta.txt",
            "lang": "pt",
            "chunk": 0,
        }
    }
    db.close()


def test_filter_by_meta_ignores_non_pushdown_values(tmp_path):
    db = CollectionDB()
    db.open(_meta_db(tmp_path))
    db.upsert_chunks(
        "doc1",
        [
            (
                "doc1::chunk_0",
                "chunks/doc1__chunk_0.txt",
                {"docid": "doc1", "lang": "en", "category": "ml"},
            ),
            (
                "doc1::chunk_1",
                "chunks/doc1__chunk_1.txt",
                {"docid": "doc1", "lang": "en", "category": "infra"},
            ),
        ],
        doc_meta={"docid": "doc1"},
    )

    candidates = ["doc1::chunk_0", "doc1::chunk_1"]
    matched = db.filter_by_meta(
        candidates,
        {
            "lang": ["en"],
            "category": ["*fra", "ml*"],
            "size": [">100"],
        },
    )

    assert matched == set(candidates)
    db.close()
