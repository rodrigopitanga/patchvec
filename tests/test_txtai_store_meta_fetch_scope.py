# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from pave.stores.txtai_store import TxtaiStore


def _seed_records(count: int) -> list[tuple[str, str, dict]]:
    return [
        (f"r{i}", "shared query token", {"lang": "en", "chunk": i})
        for i in range(count)
    ]


def test_search_fetches_meta_for_all_candidates_without_post_filters():
    store = TxtaiStore()
    tenant, collection = "tenant", "meta_scope_plain"
    store.index_records(tenant, collection, "doc", _seed_records(12))

    col_db = store._dbs[(tenant, collection)]
    seen_batches: list[list[str]] = []
    orig_get_meta_batch = col_db.get_meta_batch

    def _spy_get_meta_batch(rids: list[str]):
        seen_batches.append(list(rids))
        return orig_get_meta_batch(rids)

    col_db.get_meta_batch = _spy_get_meta_batch  # type: ignore[method-assign]

    hits = store.search(tenant, collection, "shared", k=5)
    assert len(hits) == 5
    assert seen_batches
    assert len(seen_batches[0]) > 5


def test_search_fetches_extended_meta_batch_with_post_filters():
    store = TxtaiStore()
    tenant, collection = "tenant", "meta_scope_post"
    store.index_records(tenant, collection, "doc", _seed_records(12))

    col_db = store._dbs[(tenant, collection)]
    seen_batches: list[list[str]] = []
    orig_get_meta_batch = col_db.get_meta_batch

    def _spy_get_meta_batch(rids: list[str]):
        seen_batches.append(list(rids))
        return orig_get_meta_batch(rids)

    col_db.get_meta_batch = _spy_get_meta_batch  # type: ignore[method-assign]

    hits = store.search(
        tenant,
        collection,
        "shared",
        k=5,
        filters={"lang": "*n"},
    )
    assert len(hits) == 5
    assert seen_batches
    assert len(seen_batches[0]) > 5
