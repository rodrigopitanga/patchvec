# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from unittest.mock import patch

from pave.metadb import CollectionDB
from pave.stores.faiss import FaissStore


def test_has_doc_recovers_from_closed_cached_db():
    store = FaissStore()
    tenant, collection, docid = "acme", "race_has_doc", "DOC-1"
    store.index_records(
        tenant,
        collection,
        docid,
        [("0", "cache close race probe", {"lang": "en"})],
    )

    # Simulate a stale cached CollectionDB object that was already closed.
    store._dbs[(tenant, collection)].close()

    # Should not raise "Cannot operate on a closed database."
    assert store.has_doc(tenant, collection, docid) is True


def test_search_recovers_from_closed_cached_db():
    store = FaissStore()
    tenant, collection, docid = "acme", "race_search", "DOC-2"
    store.index_records(
        tenant,
        collection,
        docid,
        [("0", "semantic probe text", {"lang": "en"})],
    )

    # Simulate stale cached CollectionDB while embeddings stay cached.
    store._dbs[(tenant, collection)].close()

    hits = store.search(tenant, collection, "semantic", k=1)
    assert len(hits) == 1
    assert hits[0].meta.get("docid") == docid


def test_delete_collection_evicts_cache_before_close():
    store = FaissStore()
    tenant, collection = "acme", "delete_order"
    store.load_or_init(tenant, collection)
    key = (tenant, collection)
    col_db = store._dbs[key]
    seen: dict[str, bool] = {}
    orig_close = col_db.close

    def _spy_close() -> None:
        seen["present_during_close"] = key in store._dbs
        orig_close()

    col_db.close = _spy_close  # type: ignore[method-assign]

    store.delete_collection(tenant, collection)

    assert seen.get("present_during_close") is False


def test_rename_collection_evicts_old_cache_before_close():
    store = FaissStore()
    tenant, old_name, new_name = "acme", "old_order", "new_order"
    store.load_or_init(tenant, old_name)
    old_key = (tenant, old_name)
    col_db = store._dbs[old_key]
    seen: dict[str, bool] = {}
    orig_close = col_db.close

    def _spy_close() -> None:
        seen["present_during_close"] = old_key in store._dbs
        orig_close()

    col_db.close = _spy_close  # type: ignore[method-assign]

    store.rename_collection(tenant, old_name, new_name)

    assert seen.get("present_during_close") is False


def test_has_doc_fallback_opens_read_only():
    """Fallback CollectionDB opens read-only (no _wconn)."""
    store = FaissStore()
    tenant, collection = "acme", "ro_fallback"
    docid = "DOC-RO"
    store.index_records(
        tenant, collection, docid,
        [("0", "read-only probe", {"lang": "en"})],
    )

    # Close and remove cached DB to force fallback path
    store._dbs[(tenant, collection)].close()
    del store._dbs[(tenant, collection)]

    opened: list[CollectionDB] = []
    _orig_open = CollectionDB.open

    def _spy_open(self, path, *, read_only=False):
        opened.append(self)
        _orig_open(self, path, read_only=read_only)

    with patch.object(CollectionDB, "open", _spy_open):
        result = store.has_doc(tenant, collection, docid)

    assert result is True
    assert len(opened) == 1
    assert opened[0]._wconn is None
