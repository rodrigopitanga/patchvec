# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

import pytest
from pave.service import ingest_document as svc_ingest, ServiceError
from pave.stores.faiss import FaissStore

@pytest.fixture
def store(monkeypatch, tmp_path):
    # isolate data dir; embedder is monkeypatched in global conftest
    from pave import config as cfg_mod
    class DummyCFG:
        data_dir = str(tmp_path / "data")

        def get(self, key, default=None):
            if key.endswith("embed_model"):
                return (
                    "sentence-transformers/paraphrase-multilingual-"
                    "MiniLM-L12-v2"
                )
            if key.endswith("vector_backend"):
                return "faiss"
            return default

    monkeypatch.setattr(cfg_mod, "CFG", DummyCFG(), raising=True)
    return FaissStore()

def _csv_bytes(s: str) -> bytes:
    return s.encode("utf-8")

def test_csv_default_include_all_minus_meta(store):
    # header: a,b,c ; meta=b ; include not given => text must contain a,c and NOT b
    csv = "a,b,c\nx,metaY,z\n"
    out = svc_ingest(
        store, "t", "c", "f.csv", _csv_bytes(csv), "D", {"lang": "pt"},
        csv_options={"has_header": "yes", "meta_cols": "b", "include_cols": ""}
    )
    assert out["ok"] and out["chunks"] == 1

    # text assertions (default include excludes meta)
    hits = store.search("t", "c", "x", k=5)
    assert hits
    txt = hits[0].text
    assert "a: x" in txt
    assert "c: z" in txt
    assert "b:" not in txt

    # meta persisted: filter by meta should find the row
    hits_meta = store.search("t", "c", "x", k=5, filters={"b": "metaY"})
    assert hits_meta

def test_csv_include_by_indices_no_header(store):
    # no header; include 1,3 ; meta 2
    csv = "x,metaY,z\n"
    out = svc_ingest(
        store, "t2", "c2", "f2.csv", _csv_bytes(csv), "D2", None,
        csv_options={"has_header": "no", "meta_cols": "2", "include_cols": "1,3"}
    )
    assert out["ok"] and out["chunks"] == 1

    hits = store.search("t2", "c2", "x", k=5)
    assert hits
    txt = hits[0].text
    assert "col_0: x" in txt
    assert "col_2: z" in txt
    assert "col_1:" not in txt  # excluded as meta

    # meta persisted under synthesized header
    hits_meta = store.search("t2", "c2", "x", k=5, filters={"col_1": "metaY"})
    assert hits_meta

def test_csv_refuse_names_without_header(store):
    # names specified but header disabled -> must raise
    csv = "x,metaY,z\n"
    with pytest.raises(ServiceError) as excinfo:
        svc_ingest(
            store, "t3", "c3", "f3.csv", _csv_bytes(csv), "D3", None,
            csv_options={"has_header": "no", "meta_cols": "b", "include_cols": ""}
        )
    assert excinfo.value.code == "invalid_csv_options"


def test_ingest_rejects_colliding_sanitized_doc_metadata_keys(store):
    with pytest.raises(ServiceError) as excinfo:
        svc_ingest(
            store,
            "t4",
            "c4",
            "f4.txt",
            _csv_bytes("hello world"),
            "D4",
            {"doc id": "shadow-docid"},
        )
    assert excinfo.value.code == "invalid_metadata_keys"
    assert "sanitize to 'docid'" in excinfo.value.message


def test_csv_ingest_rejects_colliding_sanitized_chunk_metadata_keys(store):
    csv = "a!,a?\nleft,right\n"
    with pytest.raises(ServiceError) as excinfo:
        svc_ingest(
            store,
            "t5",
            "c5",
            "f5.csv",
            _csv_bytes(csv),
            "D5",
            None,
            csv_options={
                "has_header": "yes",
                "meta_cols": "a!,a?",
                "include_cols": "",
            },
        )
    assert excinfo.value.code == "invalid_metadata_keys"
    assert "sanitize to 'a'" in excinfo.value.message


def test_ingest_rejects_metadata_key_sanitized_to_reserved_text(store):
    with pytest.raises(ServiceError) as excinfo:
        svc_ingest(
            store,
            "t6",
            "c6",
            "f6.txt",
            _csv_bytes("hello world"),
            "D6",
            {"te xt": "shadow-text"},
        )
    assert excinfo.value.code == "invalid_metadata_keys"
    assert "reserved key 'text'" in excinfo.value.message


def test_ingest_sanitizes_sqlish_doc_metadata_value_and_exact_filter_matches(store):
    raw_value = "x'; DROP TABLE chunk_meta; --"
    out = svc_ingest(
        store,
        "t7",
        "c7",
        "f7.txt",
        _csv_bytes("hello world"),
        "D7",
        {"so urce": raw_value},
    )
    assert out["ok"] is True

    hits = store.search(
        "t7",
        "c7",
        "hello",
        k=5,
        filters={"so urce": raw_value},
    )
    assert len(hits) == 1
    assert hits[0].meta["source"] == FaissStore._sanit_sql(raw_value)
