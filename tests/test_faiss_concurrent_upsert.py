# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

import pytest
import time
import json
from concurrent.futures import ThreadPoolExecutor
from pave.stores.faiss import FaissStore, Record, collection_lock
from pave.config import get_cfg

REC0 = ("doc::0", "texto A", "{}")
REC1 = ("doc::1", "texto B", "{}")

@pytest.mark.skip(
    reason=(
        "Intentional race condition can cause SQLite segfault on "
        "Python 3.14+"
    )
)
def test_concurrent_upsert_without_lock_eventually_fails(cfg):
    store = FaissStore()
    tenant, coll = "tenantX", "collRace"
    store.load_or_init(tenant, coll)
    emb = store._emb[(tenant, coll)]

    def unsafe_upsert(data):
        id, _, _ = data
        emb.delete(id)
        emb.upsert([data])
        time.sleep(0.05)
        store.save(tenant, coll)
    failed_once = False
    for _ in range(100):
        with ThreadPoolExecutor(max_workers=2) as ex:
            ex.submit(unsafe_upsert, REC0)
            ex.submit(unsafe_upsert, REC1)
        results = store.search(tenant, coll, "texto", 5)
        texts = [r.text for r in results]
        if not ("texto A" in texts and "texto B" in texts):
            failed_once = True
            break
    assert failed_once, "Race condition not detected"

def test_concurrent_upsert_with_manual_lock(cfg):
    store = FaissStore()
    tenant, coll = "tenantY", "collSafe"
    store.load_or_init(tenant, coll)
    backend = store._emb[(tenant, coll)]
    col_db = store._dbs[(tenant, coll)]

    def safe_upsert(data):
        with collection_lock(tenant, coll):
            rid, text, meta = data
            chunk_path = f"chunks/{store._urid_to_fname(rid)}"
            parsed_meta = json.loads(meta) if isinstance(meta, str) else meta
            parsed_meta = dict(parsed_meta or {})
            parsed_meta["docid"] = "doc"
            store._save_chunk_text(tenant, coll, rid, text)
            col_db.upsert_chunks("doc", [(rid, chunk_path, parsed_meta)])
            backend.delete([rid])
            vectors = store._embedder.encode([text])
            backend.add([rid], vectors)
            time.sleep(0.05)
            store.save(tenant, coll)

    for _ in range(100):
        with ThreadPoolExecutor(max_workers=2) as ex:
            ex.submit(safe_upsert, REC0)
            ex.submit(safe_upsert, REC1)
        results = store.search(tenant, coll, "texto", 5)
        texts = [r.text for r in results]
        assert "texto A" in texts and "texto B" in texts,\
            "Inconsistent state detected despite locking (manual test)"

def test_concurrent_upsert_with_lock_always_consistent(cfg):
    store = FaissStore()
    tenant, coll = "tenantZ", "collSafe"
    store.load_or_init(tenant, coll)
    emb = store._emb[(tenant, coll)]

    def safe_upsert(data):
        store.index_records(tenant, coll, "doc", [data])

    for _ in range(100):
        with ThreadPoolExecutor(max_workers=2) as ex:
            ex.submit(safe_upsert, REC0)
            ex.submit(safe_upsert, REC1)
        results = store.search(tenant, coll, "texto", 5)
        texts = [r.text for r in results]
        assert "texto A" in texts and "texto B" in texts,\
            "Inconsistent state detected despite locking (main codepath)"
