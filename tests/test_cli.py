import os, json
import pathlib
import pytest
from pave import cli as pvcli
from conftest import DummyStore

def test_cli_flow(tmp_path):
    pvcli.store = DummyStore()
    main = pvcli.main_cli
    main(["create-collection", "acme", "invoices"])
    sample = tmp_path / "s.txt"
    sample.write_text("one two three")
    main(["upload", "acme", "invoices", str(sample), "--docid", "D1", "--metadata", '{"k":"v"}'])
    main(["search", "acme", "invoices", "two", "-k", "3"])
    main(["delete-collection", "acme", "invoices"])

# Minimal FakeEmbeddings to avoid model downloads (mirrors the one in test_txtai_store)
class _FakeEmbeddings:
    def __init__(self, config):
        self.config = config
        self._docs = {}  # rid -> (text, meta_json)

    def index(self, docs):
        for rid, text, meta_json in docs:
            assert isinstance(meta_json, str)
            self._docs[rid] = (text, meta_json)

    def search(self, query, k):
        q = (query or "").lower()
        matches = []
        for rid, (text, _) in self._docs.items():
            t = (text or "").lower()
            if q in t:
                # txtai returns dict entries when content=True
                matches.append({"id": rid, "score": float(len(q)), "text": text})
        return matches[:k]

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

@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    # Patch CFG.data_dir and CFG.get like in store tests
    from pave import config as cfg_mod
    class _DummyCFG:
        data_dir = str(tmp_path / "data")
        def get(self, key, default=None):
            if key.endswith("embed_model"):
                return "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            if key.endswith("vector_backend"):
                return "faiss"
            return default
    monkeypatch.setattr(cfg_mod, "CFG", _DummyCFG(), raising=True)

    # Use real TxtaiStore in CLI but swap Embeddings with fake
    import pave.stores.txtai_store as store_mod
    monkeypatch.setattr(store_mod, "Embeddings", _FakeEmbeddings, raising=True)

    # Rebuild CLI.store with the patched CFG+Embeddings
    import importlib
    from pave import cli as pvcli
    importlib.reload(pvcli)  # ensures store = get_store(CFG) runs with our patches
    return pvcli, tmp_path

def test_cli_upload_on_fresh_collection_with_empty_index_dir(cli_env):
    pvcli, tmp_path = cli_env
    tenant, coll = "acme", "invoices"

    # Pre-create empty index dir to reproduce FAISS read_index crash path
    base = tmp_path / "data" / tenant / coll
    (base / "index").mkdir(parents=True, exist_ok=True)

    # Prepare sample file
    sample = tmp_path / "s.txt"
    sample.write_text("one two three quatro cinco")

    # Create collection then upload (should not crash even with empty index dir)
    pvcli.main_cli(["create-collection", tenant, coll])
    pvcli.main_cli(["upload", tenant, coll, str(sample), "--docid", "DOC1", "--metadata", '{"lang":"pt"}'])
    base = pvcli.store._base_path(tenant, coll)  # ok in tests
    catp = os.path.join(base, "catalog.json")
    assert os.path.isfile(catp), "catalog.json must exist after upload"
    with open(catp, "r", encoding="utf-8") as f:
        catalog = json.load(f)
    assert "DOC1" in catalog and len(catalog["DOC1"]) >= 1, "catalog must map DOC1 to >=1 chunk id"

def test_cli_search_returns_matches(cli_env):
    pvcli, tmp_path = cli_env
    tenant, coll = "acme", "invoices"
    base = tmp_path / "data" / tenant / coll
    sample = tmp_path / "s2.txt"
    sample.write_text("O avião sobrevoa o oceano. Mapas e correntes.")

    pvcli.main_cli(["create-collection", tenant, coll])
    pvcli.main_cli(["upload", tenant, coll, str(sample), "--docid", "DOC2", "--metadata", '{"lang":"pt"}'])

    # Assert via the actual store adapter (bypasses printed JSON)
    hits = pvcli.store.search(tenant, coll, "avião", k=5)
    base = pvcli.store._base_path(tenant, coll)
    catp = os.path.join(base, "catalog.json")
    assert os.path.isfile(catp), "catalog.json must exist"
    assert len(hits) >= 1
    assert any("docid" in h["meta"] and h["meta"]["docid"] == "DOC2" \
               for h in hits)
