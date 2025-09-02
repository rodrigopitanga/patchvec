# (C) 2025 Rodrigo Rodrigues da Silva
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
from pave.service import ingest_document as svc_ingest, _default_docid
from pave.stores.txtai_store import TxtaiStore
from utils import FakeEmbeddings
import pave.stores.txtai_store as store_mod

@pytest.fixture
def store(monkeypatch, tmp_path):
    # temp data dir + fake embeddings
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

def _b(s: str) -> bytes: return s.encode("utf-8")

def test_default_docid_from_filename_rules():
    assert _default_docid("bncc_ef.pdf") == "BNCC_EF_PDF"
    assert _default_docid("bncc ef v2.csv") == "BNCC_EF_V2_CSV"
    assert _default_docid("bncc-ef!.txt") == "BNCC_EF_TXT"
    val = _default_docid("...")
    assert val.startswith("PVDOC_") and len(val) > 6

def test_ingest_without_docid_uses_filename_based_docid(store):
    out = svc_ingest(store, "t", "c", "bncc_ef.csv", _b("x,y\n1,2\n"), None, None,
                     csv_options={"has_header":"yes"})
    assert out["ok"]
    assert out["docid"] == "BNCC_EF_CSV"

def test_ingest_with_explicit_docid_wins(store):
    out = svc_ingest(store, "t2", "c2", "whatever.txt", _b("hello"), "DOC123", None)
    assert out["ok"] and out["docid"] == "DOC123"
