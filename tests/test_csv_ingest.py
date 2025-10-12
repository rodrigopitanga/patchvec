# (C) 2025 Rodrigo Rodrigues da Silva
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from pave.service import ingest_document as svc_ingest
from pave.stores.txtai_store import TxtaiStore
import pave.stores.txtai_store as store_mod
from utils import FakeEmbeddings

@pytest.fixture
def store(monkeypatch, tmp_path):
    # isolate data dir + swap Embeddings to a fake
    from pave import config as cfg_mod
    class DummyCFG:
        data_dir = str(tmp_path / "data")
        def get(self, key, default=None):
            if key.endswith("embed_model"): return "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            if key.endswith("vector_backend"): return "faiss"
            return default
    monkeypatch.setattr(cfg_mod, "CFG", DummyCFG(), raising=True)
    monkeypatch.setattr(store_mod, "Embeddings", FakeEmbeddings, raising=True)
    return TxtaiStore()

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
    txt = hits[0]["text"]
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
    txt = hits[0]["text"]
    assert "col_0: x" in txt
    assert "col_2: z" in txt
    assert "col_1:" not in txt  # excluded as meta

    # meta persisted under synthesized header
    hits_meta = store.search("t2", "c2", "x", k=5, filters={"col_1": "metaY"})
    assert hits_meta

def test_csv_refuse_names_without_header(store):
    # names specified but header disabled -> must raise
    csv = "x,metaY,z\n"
    with pytest.raises(ValueError):
        svc_ingest(
            store, "t3", "c3", "f3.csv", _csv_bytes(csv), "D3", None,
            csv_options={"has_header": "no", "meta_cols": "b", "include_cols": ""}
        )
