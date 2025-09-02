# Covers: index_records() (JSON meta), search() (non-null text), filters, purge_doc()

import json
import types
import builtins
import os
import io
import pytest
from pathlib import Path

# --- Fake Embeddings (no model downloads) ------------------------------------
class FakeEmbeddings:
    """
    Minimal drop-in for txtai. Stores (id, text, meta_json) in-memory and on disk.
    """
    def __init__(self, config):
        self.config = config
        self._docs = {}  # id -> (text, meta_json)

    # txtai API used by TxtaiStore
    def index(self, docs):
        # docs: list[(id, text, meta_json)]
        for rid, text, meta_json in docs:
            assert isinstance(meta_json, str)  # must be JSON string
            self._docs[rid] = (text, meta_json)

    def search(self, query, k):
        # naive contains search, highest score first by length match
        matches = []
        q = (query or "").lower()
        for rid, (text, meta_json) in self._docs.items():
            t = (text or "").lower()
            if q in t:
                score = float(min(len(q), len(t)))  # arbitrary stable score
                matches.append({"id": rid, "score": score, "text": text})
        # return top-k dicts like txtai does
        return sorted(matches, key=lambda r: r["score"], reverse=True)[:k]

    def lookup(self, ids):
        return {rid: self._docs.get(rid, ("", ""))[0] for rid in ids}

    def delete(self, ids):
        for rid in ids:
            self._docs.pop(rid, None)

    def save(self, path):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "_fake_index.json"), "w", encoding="utf-8") as f:
            json.dump(self._docs, f, ensure_ascii=False)

    def load(self, path):
        p = os.path.join(path, "_fake_index.json")
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                self._docs = json.load(f)

# --- Fixtures ----------------------------------------------------------------
@pytest.fixture(autouse=True)
def patch_cfg_and_embeddings(monkeypatch, tmp_path):
    """
    - Force data_dir into a temp folder
    - Replace txtai Embeddings with FakeEmbeddings
    """
    # Patch CFG
    from pave import config as cfg_mod
    # CFG is used like CFG.data_dir and CFG.get(...), so ensure both exist
    class DummyCFG:
        data_dir = str(tmp_path / "data")
        def get(self, key, default=None):
            # default multilingual model path -> irrelevant in fake
            if key.endswith("embed_model"):
                return "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            if key.endswith("vector_backend"):
                return "faiss"
            return default
    monkeypatch.setattr(cfg_mod, "CFG", DummyCFG(), raising=True)

    # Patch Embeddings used inside TxtaiStore
    import pave.stores.txtai_store as store_mod
    monkeypatch.setattr(store_mod, "Embeddings", FakeEmbeddings, raising=True)

    yield

@pytest.fixture
def store():
    from pave.stores.txtai_store import TxtaiStore
    return TxtaiStore()

# --- Tests -------------------------------------------------------------------
def test_index_and_search_pt_text(store):
    # Portuguese content; ensure non-null texts returned
    recs = [
        {"id": "doc::0", "content": "Um avião sobrevoa o oceano.", "metadata": {"lang": "pt"}},
        {"id": "doc::1", "content": "Mapas do fundo do mar são fascinantes.", "metadata": {"lang": "pt"}},
    ]
    n = store.index_records("acme", "undersea", "d1", recs)
    assert n == 2

    hits = store.search("acme", "undersea", "avião", k=5)
    assert len(hits) >= 1
    assert hits[0]["text"] is not None and "avião" in hits[0]["text"].lower() or "aviao" in hits[0]["text"].lower()

def test_meta_json_and_filters(store):
    recs = [
        {"id": "x::0", "content": "Olá mundo", "metadata": {"lang": "pt"}},
        {"id": "x::1", "content": "Hello world", "metadata": {"lang": "en"}},
    ]
    store.index_records("ten", "c1", "docx", recs)

    # Filters should select only lang=en
    hits = store.search("ten", "c1", "world", k=5, filters={"lang": "en"})
    assert len(hits) == 1
    assert hits[0]["meta"]["lang"] == "en"

    # Ensure meta was JSON-encoded internally (FakeEmbeddings asserts this)

def test_purge_doc_removes_ids(store):
    recs = [
        {"id": "y::0", "content": "primeiro", "metadata": {}},
        {"id": "y::1", "content": "segundo", "metadata": {}},
    ]
    store.index_records("ten", "c2", "docy", recs)
    # sanity: present
    assert store.search("ten", "c2", "primeiro", k=3)

    removed = store.purge_doc("ten", "c2", "docy")
    assert removed == 2

    # now no matches
    hits = store.search("ten", "c2", "primeiro", k=3)
    assert hits == []

def test_load_or_init_handles_empty_index_dir(store, tmp_path):
    """
    Repro of FAISS crash: empty ./data/T/C/index/ existed -> em.load() tried to read non-existent embeddings.
    Expectation: store should initialize fresh instead of loading.
    """
    tenant, coll = "tnew", "cnew"

    # Pre-create empty index dir to mimic the broken state
    base = os.path.join(tmp_path, "data", tenant, coll)
    os.makedirs(os.path.join(base, "index"), exist_ok=True)

    # Ingest one record; should not raise, and should persist fake index json
    recs = [{"id": "r::0", "content": "hello world", "metadata": {"lang": "en"}}]
    n = store.index_records(tenant, coll, "DOC", recs)
    assert n == 1

    # force a save; the fake backend writes a sentinel file we can assert on
    store.save(tenant, coll)

    # resolve base via the store (avoid tmp_path vs CFG.data_dir drift)
    base = store._base_path(tenant, coll)  # ok to use a protected helper in tests
    fake_idx = os.path.join(base, "index", "_fake_index.json")
    assert os.path.isfile(fake_idx), "fake index file must exist after save"
