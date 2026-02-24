# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import types
import builtins
import os
import io
import pytest
from pathlib import Path

pytestmark = pytest.mark.slow
from utils import FakeEmbeddings

# --- Fixtures ----------------------------------------------------------------
@pytest.fixture(autouse=True)
def store(app):
    return app.state.store

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
    text = hits[0].text or ""
    assert "avião" in text.lower() or "aviao" in text.lower()

def test_index_two_docs_no_purge(store):
    # Portuguese content; ensure non-null texts returned
    recs1 = [
        {"id": "doc1::0", "content": "Submarino amarelo.", "metadata": {"lang": "pt"}},
    ]
    recs2 = [
        {"id": "doc2::0", "content": "Veludosas vozes.", "metadata": {"lang": "pt"}},
    ]
    n = store.index_records("acme", "undersea2", "doc1", recs1)
    assert n == 1

    n = store.index_records("acme", "undersea2", "doc2", recs2)
    assert n == 1

    hits = store.search("acme", "undersea2", "amarelo", k=5)
    assert ("purge_doc", "acme", "undersea2", "doc1") not in store.calls
    assert len(hits) >= 1
    assert hits[0].text is not None and "submarino" in hits[0].text.lower()

    recs3 = [
        {"id": "doc3::0", "content": "Som amarelo.", "metadata": {"lang": "pt"}},
    ]
    n = store.index_records("acme", "undersea2", "doc3", recs3)
    assert n == 1

    hits = store.search("acme", "undersea2", "amarelo", k=5)
    assert len(hits) >= 2
    assert hits[0].text is not None and "amarelo" in hits[0].text.lower()

def test_index_adds_docid_prefix(store):
    recs = [
        {"id": "0", "content": "bicicleta verde.", "metadata": {"lang": "pt"}},
    ]
    n = store.index_records("acme", "cycling", "docbike", recs)
    assert n == 1
    hits = store.search("acme", "cycling", "bicicleta", k=5)
    assert hits[0].text is not None and "bicicleta" in hits[0].text.lower()
    assert hits[0].text is not None and "verde" in hits[0].text.lower()
    assert hits[0].id is not None and "docbike::0" == hits[0].id

def test_chunk_sidecar_preserves_crlf(store):
    text = "First line\r\nSecond line\r\n"
    recs = [
        {"id": "0", "content": text, "metadata": {"lang": "en"}},
    ]

    n = store.index_records("acme", "crlf", "doccrlf", recs)
    assert n == 1

    stored = store.impl._load_chunk_text("acme", "crlf", "doccrlf::0")
    assert stored == text

def test_meta_json_and_filters(store):
    recs = [
        {"id": "docx::0", "content": "Olá mundo", "metadata": {"lang": "pt"}},
        {"id": "docx::1", "content": "Hello world", "metadata": {"lang": "en"}},
    ]
    store.index_records("ten", "c1", "docx", recs)

    # Filters should select only lang=en
    hits = store.search("ten", "c1", "world", k=5, filters={"lang": "en"})
    assert len(hits) == 1
    print(f"debug:: HITS: {hits}")
    assert hits[0].meta["lang"] == "en"

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
    Repro of FAISS crash: empty ./data/T/C/index/ existed -> em.load() tried to read
    non-existent embeddings. Expectation: store should initialize fresh instead of loading.
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
    # ok to use a protected helper in tests - remember we're using SpyStore
    base = store.impl._base_path(tenant, coll)
    f_idx = os.path.join(base, "index", "embeddings")
    assert os.path.isfile(f_idx), "index file must exist after save"
